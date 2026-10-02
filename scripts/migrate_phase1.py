#!/usr/bin/env python3
"""Phase 1 data migration: backfill the new canonical opportunity-model tables
(db/migrations/0001_opportunity_model.sql) from the legacy flat `jobs` table.

Ground truth: architect-redesign-docs/master-redesign-plan/DATA_MODEL.md
§5-§12 (entity schemas), §23 (historical migration rules), §24 (sequencing),
§25 (consistency checks) — post Patch 1-4.

Does NOT modify, drop, or read-write the legacy `jobs`, `daily_limits`, or
`responses` tables beyond SELECT. Safe to re-run: the whole backfill runs in
one transaction and is skipped entirely if `schema_migrations` already has a
row for this version (see `_already_migrated`).

Usage:
    python3 scripts/migrate_phase1.py [--db path/to/applications.db]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sqlite3
import sys
from pathlib import Path

MIGRATION_VERSION = "0001_opportunity_model"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "applications.db"
SCHEMA_SQL = ROOT / "db" / "migrations" / "0001_opportunity_model.sql"

MAX_ATTEMPTS = 3

# Legacy `jobs.status` values whose string IS a usable proxy for a terminal
# application_attempts.outcome (DATA_MODEL.md §23.6: "a legacy row that
# already carries a terminal recorded outcome"). Every status in this map
# gets execution_phase = OBSERVED.
STATUS_TO_OUTCOME = {
    "submission_unconfirmed": "SUBMISSION_UNCONFIRMED",
    "blocked_antibot": "CHANNEL_BLOCKED",
    "captcha_required": "CHANNEL_BLOCKED",
    "form_changed": "RETRYABLE_FAILURE",
    "failed": "TERMINAL_FAILURE",
    "unsupported_channel": "UNSUPPORTED_CHANNEL",
    # "submitted" is handled specially (evidence-gated, §23.5).
}

# Legacy statuses that imply an attempt happened (attempts>0 observed in this
# repo's data for these) but whose status string describes a LATER
# opportunity-level fate, not the attempt's own result. DATA_MODEL.md §23.6:
# "no recorded outcome and no way to determine whether external work began"
# -> conservative execution_phase = SUBMIT_INTENT, outcome left NULL.
NO_OUTCOME_STATUSES = {"expired", "filtered", "tailored"}

ATTEMPT_IMPLYING_STATUSES = (
    set(STATUS_TO_OUTCOME) | {"submitted"} | NO_OUTCOME_STATUSES
)

CHANNELS_TO_SEED = ["indeed", "wwr", "wellfound", "greenhouse", "lever", "ashby"]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def sha256(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def build_canonical_key(company: str, title: str, url: str) -> str:
    """DATA_MODEL.md §5.3 identity hierarchy: prefer a reliable source-specific
    job ID, then a reliable ATS/posting ID, then a normalized composite with
    enough discriminating information to avoid false merges. Neither of the
    first two tiers is reliably extractable from the legacy `jobs` table (no
    separate per-source job-id column exists; `ats_meta` is an unparsed JSON
    blob of varying shape per ATS). We therefore use the §5.3 fallback
    composite (normalized company + normalized title) and append the legacy
    `url`, which is UNIQUE NOT NULL in `jobs`, as the discriminator that
    guarantees no false merge between two postings that happen to share a
    company+title string. This is a one-time historical backfill of already
    -closed/static legacy rows, not an ongoing re-discovery identity scheme,
    so using the (already unique) legacy URL as part of the key here does not
    reintroduce the §5.4 "canonical identity does not equal source URL"
    problem that rule exists to prevent for live re-discovery.
    """
    return f"{normalize(company)}::{normalize(title)}::{url}"


def compute_age_band(age_reference_at: str | None, is_expired_status: bool) -> str:
    if is_expired_status:
        return "EXPIRED"
    if not age_reference_at:
        return "EXPIRED"
    try:
        ref = dt.datetime.fromisoformat(age_reference_at.replace("Z", ""))
        if ref.tzinfo is not None:
            ref = ref.astimezone(dt.timezone.utc).replace(tzinfo=None)
    except ValueError:
        return "EXPIRED"
    days = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - ref).days
    if days <= 3:
        return "0_3D"
    if days <= 7:
        return "4_7D"
    if days <= 14:
        return "8_14D"
    if days <= 21:
        return "15_21D"
    return "EXPIRED"


def _already_migrated(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,)
    ).fetchone()
    return row is not None


def apply_ddl(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL.read_text())


def backfill_opportunities(conn: sqlite3.Connection) -> dict[int, int]:
    """Returns {jobs.id: opportunity_id} for use by later backfill steps."""
    job_to_opp: dict[int, int] = {}
    rows = conn.execute(
        """
        SELECT id, url, company, title, location, job_board, salary_min,
               salary_max, date_posted, score, score_reason, status,
               status_reason, tier, created_at, updated_at, description, attempts
        FROM jobs
        """
    ).fetchall()

    for r in rows:
        (job_id, url, company, title, location, job_board, salary_min,
         salary_max, date_posted, score, score_reason, status,
         status_reason, tier, created_at, updated_at, description, attempts) = r

        canonical_key = build_canonical_key(company, title, url)

        is_expired_status = status == "expired"
        has_score = score is not None
        # NO_OUTCOME_STATUSES (expired/filtered/tailored) only count as "an
        # attempt happened" when the legacy attempts counter is actually >0;
        # most expired/filtered rows never had an attempt at all (see
        # backfill_application_attempts' matching WHERE clause).
        no_outcome_with_attempt = status in NO_OUTCOME_STATUSES and (attempts or 0) > 0
        implies_attempt = (
            status in STATUS_TO_OUTCOME or status == "submitted" or no_outcome_with_attempt
        )

        # --- current_open_state ---
        current_open_state = "EXPIRED" if is_expired_status else "UNKNOWN"

        # --- age_basis / age_reference_at ---
        if date_posted:
            age_basis = "SOURCE_PUBLICATION_TIMESTAMP"
            age_reference_at = date_posted
        else:
            age_basis = "FIRST_SEEN_AT_FALLBACK"
            age_reference_at = created_at
        age_band = compute_age_band(age_reference_at, is_expired_status)

        # --- hard_eligibility_state / reason ---
        if no_outcome_with_attempt:
            # A real attempt happened (attempts>0) even though the status
            # string later became expired/filtered/tailored; keep it
            # ELIGIBLE so the ambiguous attempt stays reconcilable rather
            # than being hidden behind an ineligibility flag.
            hard_eligibility_state = "ELIGIBLE"
            hard_eligibility_reason = None
        elif status in ("filtered", "skipped"):
            hard_eligibility_state = "INELIGIBLE"
            hard_eligibility_reason = status_reason
        elif status == "unsupported_channel":
            hard_eligibility_state = "INELIGIBLE"
            hard_eligibility_reason = "NO_SUPPORTED_ROUTE"
        elif is_expired_status and not implies_attempt:
            hard_eligibility_state = "ELIGIBLE" if has_score else "UNKNOWN"
            hard_eligibility_reason = None
        else:
            hard_eligibility_state = "ELIGIBLE"
            hard_eligibility_reason = None

        # --- fit_state / fit_score / fit_reasons ---
        fit_state = "EVALUATED" if has_score else "NOT_EVALUATED"

        # --- application_state ---
        if no_outcome_with_attempt:
            # expired / filtered(attempts>0) / tailored(attempts>0): an attempt
            # happened but its own result is not recorded -> conservative
            # AWAITING_RECONCILIATION (mirrors the "ambiguous submit" mapping
            # in DATA_MODEL.md §5.9 since we cannot rule out a submit occurred).
            application_state = "AWAITING_RECONCILIATION"
        elif status in ("filtered", "skipped"):
            application_state = "OBSERVED"
        elif status == "unsupported_channel":
            application_state = "OBSERVED"
        elif status in ("scored",):
            application_state = "READY"
        elif status == "submitted":
            # Evidence-gated per §23.5; see backfill_application_attempts for
            # the per-row evidence check. We mirror the same evidence rule
            # here so opportunity state and attempt outcome never disagree.
            application_state = None  # resolved below using evidence check
        elif status in ("submission_unconfirmed",):
            application_state = "AWAITING_RECONCILIATION"
        elif status in ("blocked_antibot", "captcha_required"):
            application_state = "MANUAL_REVIEW"
        elif status == "form_changed":
            application_state = "READY"
        elif status == "failed":
            application_state = "MANUAL_REVIEW"
        elif status == "tailored":
            application_state = "READY"  # attempts == 0 case (none in this dataset)
        elif is_expired_status:
            application_state = "EXPIRED"
        else:
            application_state = "OBSERVED"

        if status == "submitted":
            has_evidence = bool(conn.execute(
                "SELECT 1 FROM jobs WHERE id = ? AND ("
                "  (submission_evidence IS NOT NULL AND submission_evidence != '')"
                "  OR (screenshot_path IS NOT NULL AND screenshot_path != '')"
                ")",
                (job_id,),
            ).fetchone())
            application_state = "COMPLETED" if has_evidence else "AWAITING_RECONCILIATION"

        now = now_iso()
        cur = conn.execute(
            """
            INSERT INTO opportunities (
                canonical_key, identity_version, company_normalized, company_display,
                company_domain, job_title_normalized, job_title_display,
                location_normalized, location_display, employment_type, work_mode,
                salary_min, salary_max, salary_currency, salary_basis,
                first_seen_at, first_posted_at, last_observed_at, last_verified_open_at,
                current_open_state, age_basis, age_reference_at, age_band,
                hard_eligibility_state, hard_eligibility_reason,
                fit_state, fit_score, fit_confidence, fit_reasons, core_or_stretch,
                application_state, current_attempt_id, terminal_reason,
                selected_resume_variant, current_cover_letter_ref,
                latest_description_hash, latest_application_route,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                canonical_key, 1, normalize(company), company,
                None, normalize(title), title,
                normalize(location), location, None, None,
                salary_min, salary_max, None, None,
                created_at, date_posted, updated_at, None,
                current_open_state, age_basis, age_reference_at, age_band,
                hard_eligibility_state, hard_eligibility_reason,
                fit_state, score, None, score_reason, tier,
                application_state, None, None,
                None, None,
                sha256(description), None,
                created_at, updated_at,
            ),
        )
        job_to_opp[job_id] = cur.lastrowid

    return job_to_opp


def backfill_source_observations(conn: sqlite3.Connection, job_to_opp: dict[int, int]) -> int:
    rows = conn.execute(
        """
        SELECT id, url, company, title, location, job_board, salary_min,
               salary_max, date_posted, status, ats_meta, created_at, updated_at,
               description
        FROM jobs
        """
    ).fetchall()
    count = 0
    for r in rows:
        (job_id, url, company, title, location, job_board, salary_min,
         salary_max, date_posted, status, ats_meta, created_at, updated_at,
         description) = r
        opp_id = job_to_opp[job_id]
        observation_status = "CLOSED" if status == "expired" else "ACTIVE"
        conn.execute(
            """
            INSERT INTO source_observations (
                opportunity_id, source_name, source_job_id, source_url, apply_url,
                observed_at, posted_at, open_state, company_raw, title_raw,
                location_raw, employment_type_raw, work_mode_raw,
                salary_min_raw, salary_max_raw, salary_currency_raw,
                description_hash, description_ref, raw_metadata,
                observation_status, failure_reason, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                opp_id, job_board or "unknown", None, url, None,
                updated_at, date_posted,
                "CLOSED" if status == "expired" else "OPEN",
                company, title, location, None, None,
                str(salary_min) if salary_min is not None else None,
                str(salary_max) if salary_max is not None else None,
                None,
                sha256(description), None, ats_meta,
                observation_status, None, created_at,
            ),
        )
        count += 1
    return count


def backfill_evaluation_history(conn: sqlite3.Connection, job_to_opp: dict[int, int]) -> int:
    rows = conn.execute(
        """
        SELECT id, score, score_reason, status, status_reason, updated_at
        FROM jobs
        """
    ).fetchall()
    count = 0
    for job_id, score, score_reason, status, status_reason, updated_at in rows:
        opp_id = job_to_opp[job_id]
        if score is not None:
            conn.execute(
                """
                INSERT INTO evaluation_history (
                    opportunity_id, evaluation_type, evaluated_at, policy_version,
                    input_hash, result, score, confidence, reason, model_name,
                    model_version, metadata
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (opp_id, "FIT_SCORE", updated_at, "legacy", None, "SCORED",
                 score, None, score_reason, None, None, None),
            )
            count += 1
        if status in ("filtered", "skipped", "unsupported_channel"):
            conn.execute(
                """
                INSERT INTO evaluation_history (
                    opportunity_id, evaluation_type, evaluated_at, policy_version,
                    input_hash, result, score, confidence, reason, model_name,
                    model_version, metadata
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (opp_id, "HARD_ELIGIBILITY", updated_at, "legacy", None,
                 "INELIGIBLE", None, None, status_reason, None, None, None),
            )
            count += 1
    return count


def backfill_application_attempts(conn: sqlite3.Connection, job_to_opp: dict[int, int]) -> int:
    unconditional_statuses = list(STATUS_TO_OUTCOME) + ["submitted"]
    no_outcome_statuses = list(NO_OUTCOME_STATUSES)
    rows = conn.execute(
        """
        SELECT id, status, attempts, last_attempt_at, apply_channel,
               submission_evidence, screenshot_path, created_at, updated_at
        FROM jobs
        WHERE status IN ({unconditional})
           OR (status IN ({no_outcome}) AND attempts > 0)
        """.format(
            unconditional=",".join("?" for _ in unconditional_statuses),
            no_outcome=",".join("?" for _ in no_outcome_statuses),
        ),
        tuple(unconditional_statuses) + tuple(no_outcome_statuses),
    ).fetchall()

    count = 0
    for (job_id, status, attempts, last_attempt_at, apply_channel,
         submission_evidence, screenshot_path, created_at, updated_at) in rows:
        opp_id = job_to_opp[job_id]
        attempt_number = max(attempts or 0, 1)
        claimed_at = last_attempt_at or updated_at or created_at
        channel = apply_channel or "unknown"

        if status == "submitted":
            has_evidence = bool(
                (submission_evidence and submission_evidence != "")
                or (screenshot_path and screenshot_path != "")
            )
            outcome = "SUBMITTED" if has_evidence else "SUBMISSION_UNCONFIRMED"
            execution_phase = "OBSERVED"
        elif status in STATUS_TO_OUTCOME:
            outcome = STATUS_TO_OUTCOME[status]
            execution_phase = "OBSERVED"
        else:
            # NO_OUTCOME_STATUSES: expired/filtered/tailored with attempts>0.
            # §23.6: no recorded outcome, no way to determine external-work
            # extent -> conservative SUBMIT_INTENT, outcome left NULL.
            outcome = None
            execution_phase = "SUBMIT_INTENT"

        retry_eligible = 0  # conservative default for all migrated historical rows (see report)

        evidence_json = None
        if submission_evidence:
            evidence_json = submission_evidence

        now = now_iso()
        cur = conn.execute(
            """
            INSERT INTO application_attempts (
                opportunity_id, channel, attempt_number, worker_id, claimed_at,
                lease_until, started_at, finished_at, attempt_state,
                execution_phase, outcome, error_code, error_class, retry_eligible,
                resolved_apply_url, confirmation_url, confirmation_text,
                authenticated_session_ref, evidence_json, screenshot_ref,
                email_evidence_ref, browser_signals, network_signals,
                request_trace_ref, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                opp_id, channel, attempt_number, None, claimed_at,
                None, claimed_at, claimed_at, "FINISHED",
                execution_phase, outcome, None, None, retry_eligible,
                None, None, None,
                None, evidence_json, screenshot_path,
                None, None, None,
                None, "migrated from legacy jobs.status='%s'" % status,
                created_at, updated_at,
            ),
        )
        attempt_id = cur.lastrowid
        count += 1

        # Point the opportunity's current_attempt_id at this (its only
        # migrated) attempt, and its application_state is already consistent
        # with this outcome from backfill_opportunities.
        conn.execute(
            "UPDATE opportunities SET current_attempt_id = ? WHERE opportunity_id = ?",
            (attempt_id, opp_id),
        )

    return count


def backfill_responses_v2(conn: sqlite3.Connection) -> int:
    has_old_responses = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='responses'"
    ).fetchone()
    if not has_old_responses:
        return 0

    old_rows = conn.execute(
        "SELECT message_id, from_addr, subject, received_at, classification, "
        "job_url, notified_at FROM responses"
    ).fetchall()
    if not old_rows:
        return 0

    count = 0
    for message_id, from_addr, subject, received_at, classification, job_url, notified_at in old_rows:
        opportunity_id = None
        if job_url:
            row = conn.execute(
                "SELECT opportunity_id FROM source_observations WHERE source_url = ? LIMIT 1",
                (job_url,),
            ).fetchone()
            if row:
                opportunity_id = row[0]

        conn.execute(
            """
            INSERT OR IGNORE INTO responses_v2 (
                message_id, from_addr, subject, received_at, classification,
                opportunity_id, attempt_id, job_url_observed, notified_at,
                notification_level, message_hash, correlation_reason,
                raw_message_ref, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                message_id, from_addr, subject, received_at, classification,
                opportunity_id, None, job_url, notified_at,
                None, None, None,
                None, received_at or now_iso(),
            ),
        )
        count += 1
    return count


def seed_channel_health(conn: sqlite3.Connection) -> int:
    now = now_iso()
    count = 0
    for key in CHANNELS_TO_SEED:
        conn.execute(
            """
            INSERT INTO channel_health (
                channel_key, scope, provider, status, failure_streak,
                success_count, blocked_count, rate_limit_count,
                last_success_at, last_failure_at, cooldown_until,
                last_error_class, last_error_code, health_reason,
                capability_version, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (key, "global", key, "HEALTHY", 0, 0, 0, 0,
             None, None, None, None, None, None, None, now),
        )
        count += 1
    return count


def rebuild_work_queue(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM work_queue")
    rows = conn.execute(
        """
        SELECT opportunity_id, age_band, fit_score
        FROM opportunities
        WHERE application_state = 'READY'
          AND hard_eligibility_state = 'ELIGIBLE'
          AND (age_band IS NULL OR age_band != 'EXPIRED')
        """
    ).fetchall()
    now = now_iso()
    for opp_id, age_band, fit_score in rows:
        conn.execute(
            """
            INSERT INTO work_queue (
                opportunity_id, ready_state, age_band, priority_score,
                next_attempt_at, lease_until, candidate_channel, queue_reason,
                updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (opp_id, "READY", age_band or "EXPIRED", fit_score, None, None,
             None, "migrated_phase1", now),
        )
    return len(rows)


def run_migration(conn: sqlite3.Connection) -> dict[str, int]:
    apply_ddl(conn)

    if _already_migrated(conn):
        print(f"[migrate_phase1] version {MIGRATION_VERSION} already applied — skipping backfill.")
        return {}

    counts: dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        job_to_opp = backfill_opportunities(conn)
        counts["opportunities"] = len(job_to_opp)
        counts["source_observations"] = backfill_source_observations(conn, job_to_opp)
        counts["evaluation_history"] = backfill_evaluation_history(conn, job_to_opp)
        counts["application_attempts"] = backfill_application_attempts(conn, job_to_opp)
        counts["responses_v2"] = backfill_responses_v2(conn)
        counts["channel_health"] = seed_channel_health(conn)
        counts["work_queue"] = rebuild_work_queue(conn)

        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (MIGRATION_VERSION, now_iso()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        counts = run_migration(conn)
    finally:
        conn.close()

    if counts:
        print("[migrate_phase1] Backfill complete:")
        for table, n in counts.items():
            print(f"  {table}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
