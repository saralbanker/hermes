#!/usr/bin/env python3
"""
scripts/release_manual_review.py — Legacy manual release: the ONLY way a
jobs.status='manual_review' row (exhausted VALIDATION_FAILED budget — see
src/states.py's MAX_VALIDATION_ATTEMPTS, src/apply.py's record_result) leaves that
terminal hold. No auto-expiry anywhere; this script is the sole release path.

release(url, note): refuses unless jobs.status == 'manual_review'. Resets
status='scored', cover_letter_path=NULL (forces tailor.py to regenerate through the
now-fixed facts()/candidate_text()/PROOF_BY_VARIANT before the job can reach apply.py
again), attempts=0, validation_attempts=0 (flat mutable columns, no per-attempt history
table exists in the legacy schema, so this is a plain reset, not a history-destroying
operation), status_reason='manual_release: see output/manual_review_releases.jsonl
(operational log)'.

Appends one line to output/manual_review_releases.jsonl: {ts, url, company, title,
prior_status_reason, validation_attempts_at_release, note}. That file is explicitly
operational/informational only — a human-readable breadcrumb, not a tamper-proof audit
system. No compliance guarantee is implied.

A release grants a genuinely fresh validation_attempts budget, not a permanently
truncated one — a human choosing to intervene again is not the unbounded-automatic-retry
risk the budget exists to prevent.

Usage:
    python scripts/release_manual_review.py --list            # show all manual_review rows
    python scripts/release_manual_review.py <url> [--note "why"]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from db import get_conn, init_db  # noqa: E402

ROOT = Path(__file__).parent.parent
RELEASE_LOG = ROOT / "output" / "manual_review_releases.jsonl"


class ReleaseError(RuntimeError):
    """Raised when `url` does not refer to a jobs.status='manual_review' row."""


def release(url: str, note: str = "") -> dict:
    """Release one jobs.status='manual_review' row back into the pipeline with a fresh
    validation_attempts budget. Raises ReleaseError if the row isn't in manual_review
    (including: doesn't exist at all) — never silently no-ops."""
    conn = get_conn()
    row = conn.execute(
        "SELECT url, company, title, status, status_reason, validation_attempts FROM jobs WHERE url = ?",
        (url,),
    ).fetchone()
    if row is None:
        conn.close()
        raise ReleaseError(f"no job row for url {url!r}")
    if row["status"] != "manual_review":
        conn.close()
        raise ReleaseError(
            f"refusing to release {url!r}: status is {row['status']!r}, not 'manual_review'"
        )
    prior_reason = row["status_reason"]
    validation_attempts_at_release = row["validation_attempts"] or 0
    conn.execute(
        "UPDATE jobs SET status = 'scored', cover_letter_path = NULL, attempts = 0, "
        "validation_attempts = 0, "
        "status_reason = 'manual_release: see output/manual_review_releases.jsonl (operational log)' "
        "WHERE url = ?",
        (url,),
    )
    conn.commit()
    conn.close()

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "url": url,
        "company": row["company"],
        "title": row["title"],
        "prior_status_reason": prior_reason,
        "validation_attempts_at_release": validation_attempts_at_release,
        "note": note,
    }
    RELEASE_LOG.parent.mkdir(exist_ok=True, parents=True)
    with RELEASE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def list_manual_review() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT url, company, title, status_reason, validation_attempts FROM jobs "
        "WHERE status = 'manual_review' ORDER BY company, title"
    ).fetchall()
    conn.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Release a legacy jobs.status='manual_review' row back into the pipeline."
    )
    parser.add_argument("url", nargs="?", help="The job's url (primary key in the jobs table).")
    parser.add_argument("--note", default="", help="Human-readable reason for the release.")
    parser.add_argument("--list", action="store_true", help="List all manual_review rows and exit.")
    args = parser.parse_args()

    init_db()

    if args.list or not args.url:
        rows = list_manual_review()
        if not rows:
            print("[release_manual_review] No jobs.status='manual_review' rows.")
        for r in rows:
            print(f"  {r['company']} — {r['title']} | validation_attempts={r['validation_attempts']} | {r['url']}")
            print(f"    reason: {r['status_reason']}")
        if not args.url:
            return

    try:
        entry = release(args.url, args.note)
    except ReleaseError as exc:
        print(f"[release_manual_review] REFUSED: {exc}")
        raise SystemExit(1)
    print(f"[release_manual_review] Released {entry['company']} — {entry['title']} "
          f"({entry['url']}); fresh validation_attempts budget. Logged to {RELEASE_LOG}.")


if __name__ == "__main__":
    main()
