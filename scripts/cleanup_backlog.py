#!/usr/bin/env python3
"""
scripts/cleanup_backlog.py — One-time, idempotent migration of the pre-tier
backlog onto the new tier/salary/role rules (owner overhaul, 2026-09-23).

Rules (see task spec / owner instructions):
  - NEVER touches rows with status 'submitted'.
  - LinkedIn-board rows that aren't submitted -> 'skipped' /
    'backlog:linkedin_disabled' (LinkedIn automation is disabled).
  - Rows whose dedupe_key matches a submitted row -> 'skipped' /
    'duplicate_of_submitted'.
  - For rows in discovered/scored/tailored/error: fill dedupe_key/tier/
    required_years, then re-run passes_filters()+classify_tier().
      * Failing rows -> 'filtered' (or 'expired' if the failure reason is
        staleness), reason prefixed 'backlog:'.
      * 'error' rows whose status_reason contains 'login_wall' AND now pass
        filters -> back to 'discovered' (false Cloudflare/bot-wall
        classification; they will be re-scored).
      * Other 'error' rows -> 'failed', keeping their original reason.
      * 'tailored' rows that pass -> back to 'scored', cover_letter_path set
        to NULL (old letters were fabricated pre-overhaul and must be
        regenerated — the files themselves are NOT deleted).
  - Deterministic and side-effect-free to compute twice: re-running this
    script produces the same end state (see plan_changes()).

Usage:
    python scripts/cleanup_backlog.py --dry-run   # print counts, write nothing
    python scripts/cleanup_backlog.py             # back up the DB, then apply
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from db import DB_PATH, dedupe_key as make_dedupe_key, get_conn, init_db  # noqa: E402
from filters import classify_tier, passes_filters  # noqa: E402

TARGET_STATUSES = ("discovered", "scored", "tailored", "error")


def load_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    return yaml.safe_load(open(cfg_path))


def backup_db() -> Path:
    out_dir = Path(__file__).parent.parent / "output"
    out_dir.mkdir(exist_ok=True, parents=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    dest = out_dir / f"applications.backup-cleanup-{ts}.db"
    shutil.copy2(DB_PATH, dest)
    return dest


def _job_dict(row) -> dict:
    """Build the dict passes_filters()/classify_tier() expect from a DB row.
    Note: the jobs table has no `currency` column, so job.get('currency') is
    always None here — filters.salary_ok() then applies the India floor
    (the stricter reading is not available; see report for this interpretation)."""
    return {
        "title": row["title"],
        "description": row["description"],
        "location": row["location"],
        "date_posted": row["date_posted"],
        "salary_min": row["salary_min"],
        "salary_max": row["salary_max"],
    }


def _stale_listing(row, cfg: dict) -> bool:
    """No usable posting date and first seen longer ago than max_job_age_days → assume closed."""
    from datetime import datetime, timedelta
    if row["date_posted"]:
        return False
    seen = datetime.fromisoformat(row["created_at"])
    return datetime.now() - seen > timedelta(days=cfg["search"]["max_job_age_days"])


def plan_changes(cfg: dict, conn) -> list[dict]:
    """Compute the new row state for every non-submitted job. Pure/read-only —
    makes no DB writes."""
    rows = conn.execute(
        "SELECT id, url, company, title, description, location, date_posted, "
        "salary_min, salary_max, status, status_reason, job_board, tier, "
        "required_years, dedupe_key, cover_letter_path FROM jobs "
        "WHERE status != 'submitted'"
    ).fetchall()

    submitted_keys = {
        r["dedupe_key"] for r in conn.execute(
            "SELECT dedupe_key FROM jobs WHERE status = 'submitted' AND dedupe_key IS NOT NULL"
        ).fetchall()
        if r["dedupe_key"]
    }

    updates = []
    for row in rows:
        job = _job_dict(row)
        key = make_dedupe_key(row["company"], row["title"])

        if row["status"] in TARGET_STATUSES:
            tier, years, _reason = classify_tier(job["title"] or "", job["description"] or "", cfg)
        else:
            tier, years = row["tier"], row["required_years"]

        new_status = row["status"]
        new_reason = row["status_reason"]
        new_cover_letter_path = row["cover_letter_path"]

        job_board = (row["job_board"] or "").lower()
        old_reason = row["status_reason"] or ""

        if job_board == "linkedin":
            new_status, new_reason = "skipped", "backlog:linkedin_disabled"
        elif key in submitted_keys:
            new_status, new_reason = "skipped", "duplicate_of_submitted"
        elif row["status"] in TARGET_STATUSES and _stale_listing(row, cfg):
            new_status, new_reason = "expired", "backlog:stale_listing"
        elif row["status"] == "error":
            ok, reason = passes_filters(job, cfg)
            if not ok:
                new_status = "expired" if reason in ("expired", "stale_posting") else "filtered"
                new_reason = f"backlog:{reason}"
            elif "login_wall" in old_reason or "below_overlap_threshold" in old_reason:
                # login_wall = Cloudflare misread; overlap = retired keyword gate. Re-score both.
                new_status, new_reason = "discovered", f"backlog:rescore ({old_reason[:40]})"
            else:
                new_status = "failed"  # keep original reason
        elif row["status"] in ("discovered", "scored", "tailored"):
            ok, reason = passes_filters(job, cfg)
            if not ok:
                new_status = "expired" if reason in ("expired", "stale_posting") else "filtered"
                new_reason = f"backlog:{reason}"
            elif row["status"] == "tailored":
                # pre-overhaul letters contained fabricated claims: regenerate (files kept)
                new_status, new_cover_letter_path = "scored", None
        # else: already filtered/expired/skipped/invalid/etc. — leave status/reason alone.

        updates.append({
            "id": row["id"],
            "url": row["url"],
            "old_status": row["status"],
            "status": new_status,
            "status_reason": new_reason,
            "cover_letter_path": new_cover_letter_path,
            "tier": tier,
            "required_years": years,
            "dedupe_key": key,
        })
    return updates


def apply_updates(conn, updates: list[dict]) -> None:
    conn.executemany(
        "UPDATE jobs SET status=:status, status_reason=:status_reason, "
        "cover_letter_path=:cover_letter_path, tier=:tier, "
        "required_years=:required_years, dedupe_key=:dedupe_key WHERE id=:id",
        updates,
    )
    conn.commit()


def status_counts(conn) -> Counter:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    return Counter({r["status"]: r["n"] for r in rows})


def main(dry_run: bool = False) -> None:
    init_db()
    cfg = load_config()
    conn = get_conn()

    before = status_counts(conn)
    print("[cleanup] Before:")
    for status, n in sorted(before.items()):
        print(f"  {status:<24} {n}")

    updates = plan_changes(cfg, conn)
    transitions = Counter((u["old_status"], u["status"]) for u in updates if u["old_status"] != u["status"])

    print(f"\n[cleanup] {len(updates)} non-submitted rows evaluated, "
          f"{sum(transitions.values())} would change status.")
    for (old, new), n in sorted(transitions.items()):
        print(f"  {old} -> {new}: {n}")

    if dry_run:
        print("\n[cleanup] --dry-run active: no backup taken, no rows written.")
        conn.close()
        return

    backup_path = backup_db()
    print(f"\n[cleanup] Backed up DB to {backup_path}")

    apply_updates(conn, updates)

    after = status_counts(conn)
    print("\n[cleanup] After:")
    for status, n in sorted(after.items()):
        print(f"  {status:<24} {n}")
    conn.close()
    print("\n[cleanup] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate the pre-tier job backlog (idempotent).")
    parser.add_argument("--dry-run", action="store_true", help="Print counts; write nothing.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
