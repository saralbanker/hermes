"""Source ingestion — WORKFLOW_ENGINE.md §6 Discovery Workflow:

    collect -> normalize -> source-level dedupe -> canonical identity resolution
    -> observation persistence -> opportunity refresh -> open-state evaluation
    -> age evaluation -> hard eligibility -> queue projection

Reuses src/discover.py's actual fetch logic (`collect()`, every board's
scraper) and src/filters.py's hard-eligibility logic (`passes_filters`,
`classify_tier`) rather than reimplementing either — only the PERSISTENCE
step is new: instead of the legacy `jobs` table, rows resolve through
src/engine/identity.py + src/engine/duplicates.py's `get_or_create_opportunity`
into opportunities/source_observations (§6.5 Re-observation rule — the old
"URL already in DB -> discard forever" behavior is explicitly forbidden).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import discover as _discover  # noqa: E402 — reused: collect(), _row_to_job()
import filters as _filters  # noqa: E402 — reused: passes_filters(), classify_tier()

from . import db as enginedb
from . import description_store
from . import identity
from .duplicates import get_or_create_opportunity


# Phase 7 (M7 — We Work Remotely production path, IMPLEMENTATION_ROADMAP.md §78) and
# Phase 8 (M8 — Wellfound, IMPLEMENTATION_ROADMAP.md §82): both are "redirect-sourced"
# boards whose real application destination is only known after redirect resolution at
# apply time (WORKFLOW_ENGINE.md §47's RESOLVE CHANNEL step happens AFTER claim, not at
# discovery) — src/sources_wwr.py's / src/sources_wellfound.py's own apply_channel field
# ("redirect", or an inline-detected "greenhouse"/"lever") is not a stable candidate_channel
# to filter claims on. Tag the opportunity's candidate channel by its DISCOVERY BOARD
# instead, so claim.claim_next(channel_filter="wwr"|"wellfound")
# (src/engine_apply.py::apply_wwr_via_engine / apply_wellfound_via_engine) finds every
# board-origin opportunity regardless of what it resolves to, and channel_health
# bookkeeping lands on that board's own dedicated row seeded by
# db/migrations/0001_opportunity_model.sql (via scripts/migrate_phase1.py's
# CHANNELS_TO_SEED) — not on the shared greenhouse/lever/ashby rows other sources' resolved
# routes also use (those stay untouched per §85). Every other board's apply_channel is
# already fully resolved at discovery (e.g. "indeed") and is left as-is.
_SOURCE_LEVEL_CHANNEL = {"wwr": "wwr", "wellfound": "wellfound"}


def _opportunity_defaults(job: dict, eligible: bool, reason: str, tier: str | None, now: str) -> dict:
    is_expired = reason == "expired"
    hard_state = "ELIGIBLE" if eligible else "INELIGIBLE"
    application_state = "EXPIRED" if is_expired else ("EVALUATING" if eligible else "OBSERVED")
    return dict(
        identity_version=1,
        company_normalized=identity.normalize(job.get("company")),
        company_display=job.get("company"),
        job_title_normalized=identity.normalize(job.get("title")),
        job_title_display=job.get("title"),
        location_normalized=identity.normalize(job.get("location")),
        location_display=job.get("location"),
        employment_type=None,
        salary_min=job.get("salary_min"),
        salary_max=job.get("salary_max"),
        first_seen_at=now,
        first_posted_at=job.get("date_posted"),
        last_observed_at=now,
        current_open_state="EXPIRED" if is_expired else "UNKNOWN",
        age_basis="SOURCE_PUBLICATION_TIMESTAMP" if job.get("date_posted") else "FIRST_SEEN_AT_FALLBACK",
        age_reference_at=job.get("date_posted") or now,
        age_band="EXPIRED" if is_expired else None,  # recomputed properly by the age-refresh sweep
        hard_eligibility_state=hard_state,
        hard_eligibility_reason=None if eligible else reason,
        core_or_stretch=tier,
        fit_state="NOT_EVALUATED",
        application_state=application_state,
        latest_application_route=_SOURCE_LEVEL_CHANNEL.get(job.get("job_board")) or job.get("apply_channel"),
        created_at=now,
        updated_at=now,
    )


def _refresh_existing_opportunity(
    conn: sqlite3.Connection, opportunity_id: int, job: dict, eligible: bool, reason: str, now: str
) -> None:
    """§6.5 Re-observation rule: refresh current open state + relevant
    evidence + re-evaluate current policy — but never clobber an opportunity
    that has moved past OBSERVED/EVALUATING (READY/APPLYING/COMPLETED/
    AWAITING_RECONCILIATION/MANUAL_REVIEW own their own state; a fresh
    discovery sighting must not silently reset live/terminal progress)."""
    opp = enginedb.fetch_opportunity(conn, opportunity_id)
    if opp is None:
        return
    conn.execute(
        "UPDATE opportunities SET last_observed_at = ?, updated_at = ? WHERE opportunity_id = ?",
        (now, now, opportunity_id),
    )
    if opp["application_state"] not in ("OBSERVED", "EVALUATING"):
        return
    if reason == "expired":
        conn.execute(
            "UPDATE opportunities SET application_state = 'EXPIRED', current_open_state = 'EXPIRED', "
            "age_band = 'EXPIRED', updated_at = ? WHERE opportunity_id = ?",
            (now, opportunity_id),
        )
        return
    hard_state = "ELIGIBLE" if eligible else "INELIGIBLE"
    new_app_state = "EVALUATING" if eligible else "OBSERVED"
    conn.execute(
        "UPDATE opportunities SET hard_eligibility_state = ?, hard_eligibility_reason = ?, "
        "application_state = ?, updated_at = ? WHERE opportunity_id = ?",
        (hard_state, None if eligible else reason, new_app_state, now, opportunity_id),
    )


def ingest_row(conn: sqlite3.Connection, job: dict, cfg: dict, now: str | None = None) -> dict:
    """One discovered listing -> one opportunity (new or re-observed) + one
    appended source_observations row. Returns a small result dict for
    counting (`created`, `eligible`, `opportunity_id`)."""
    now = now or enginedb.now_iso()
    url = job.get("url")
    if not url:
        return {"created": False, "eligible": False, "opportunity_id": None, "skipped": "no_url"}

    eligible, reason = _filters.passes_filters(job, cfg)
    tier, _years, _tier_reason = _filters.classify_tier(
        job.get("title") or "", job.get("description") or "", cfg
    )
    key = identity.canonical_key(job.get("company"), job.get("title"), job.get("location"))
    defaults = _opportunity_defaults(job, eligible, reason, tier, now)
    opportunity_id, created = get_or_create_opportunity(conn, key, defaults)
    if not created:
        _refresh_existing_opportunity(conn, opportunity_id, job, eligible, reason, now)

    description_ref = description_store.write(opportunity_id, job.get("description") or "")
    conn.execute(
        """
        INSERT INTO source_observations (
            opportunity_id, source_name, source_url, apply_url, observed_at,
            posted_at, open_state, company_raw, title_raw, location_raw,
            salary_min_raw, salary_max_raw, description_ref, raw_metadata,
            observation_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opportunity_id, job.get("job_board") or "unknown", url, url, now,
            job.get("date_posted"), "CLOSED" if reason == "expired" else "ACTIVE",
            job.get("company"), job.get("title"), job.get("location"),
            str(job.get("salary_min")) if job.get("salary_min") is not None else None,
            str(job.get("salary_max")) if job.get("salary_max") is not None else None,
            description_ref, job.get("ats_meta"),
            "CLOSED" if reason == "expired" else "ACTIVE", now,
        ),
    )
    return {"created": created, "eligible": eligible, "opportunity_id": opportunity_id, "skipped": None}


def run_discovery_cycle(conn: sqlite3.Connection, cfg: dict, limit: int | None = None) -> dict:
    """WORKFLOW_ENGINE.md §6, full cycle: collect (every enabled board, via
    src/discover.py, isolated per-source failures already handled there) ->
    ingest each row."""
    now = enginedb.now_iso()
    raw_df = _discover.collect(cfg, limit)
    counts = {"raw": len(raw_df), "created": 0, "re_observed": 0, "eligible": 0, "skipped": 0}
    for row in raw_df.itertuples(index=False):
        job = _discover._row_to_job(row)
        result = ingest_row(conn, job, cfg, now)
        if result["skipped"]:
            counts["skipped"] += 1
            continue
        counts["created" if result["created"] else "re_observed"] += 1
        counts["eligible"] += int(result["eligible"])
    return counts
