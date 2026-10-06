#!/usr/bin/env python3
"""
scripts/remediate_retired_project_letters.py — ONE-TIME remediation of already-cached
cover letters that mention a retired project (Shade Ledger, HeatMax, Carbon Compass),
written before F2's redaction/gate fixes existed. See the approved remediation plan §4.

DO NOT RUN THIS AGAINST db/applications.db OR output/tailored/ OUTSIDE THE §0
MAINTENANCE FREEZE (scripts/install_timers.sh's systemd timers must be stopped and the
run lock on output/hermes.lock confirmed free first — see the plan's §0 procedure). This
script mutates jobs rows and (indirectly, via forcing regeneration on the next tailor.py
run) output/tailored/ content on the live, currently-running legacy path. Never invoked
automatically by anything in this repo.

What it does, for every row whose cached cover_letter_path file mentions a retired
project AND whose status is in MUTABLE_STATUSES:
  - cover_letter_path = NULL, status = 'scored' (forces tailor.py to regenerate through
    the now-fixed facts()/candidate_text()/PROOF_BY_VARIANT before the job can reach
    apply.py again). attempts/validation_attempts are left untouched.

What it deliberately never touches, even when they contain retired-project text:
  - submission_unconfirmed rows: src/states.py documents this status as "clicked submit,
    no success signal: never retried blindly" — the original submission may have
    actually succeeded. Forcing it back into the pipeline risks a DUPLICATE submission to
    the same employer — strictly worse than a stale cached letter sitting unread. Reported
    for manual human review only, never auto-modified.
  - submitted rows: historical/immutable. Reported for audit awareness only, never
    modified.
  - any other status (filtered/expired/skipped/invalid/manual_review/applying/etc.):
    left untouched and unreported — these are terminal/inactive rows the live pipeline
    will never serve again, so remediating them has no safety value.

Retired-project detection reuses submission_gate.find_retired_project_mentions (itself
derived from project_registry.RETIRED_PROJECTS) rather than a second hardcoded name
list — project_registry.py's own module docstring is explicit that no other file may
define a second retired-name list or redaction routine. (Note: this is a deliberate,
documented deviation from the plan's own illustrative pseudocode, which sketched a
standalone `RETIRED_RE` regex literal for this script — reusing the registry-derived
gate helper instead keeps exactly one source of truth, consistent with project_registry.py's
explicit design invariant.)

Usage:
    python scripts/remediate_retired_project_letters.py --dry-run   # report only, no writes
    python scripts/remediate_retired_project_letters.py             # back up the DB, then apply
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from db import DB_PATH, get_conn, init_db  # noqa: E402
from submission_gate import find_retired_project_mentions  # noqa: E402

ROOT = Path(__file__).parent.parent

MUTABLE_STATUSES = (
    "tailored", "scored", "form_changed", "network_error",
    "failed", "blocked_antibot", "captcha_required",
)
# submission_unconfirmed and submitted are both handled specially — see module docstring.
REPORT_ONLY_STATUSES = ("submission_unconfirmed", "submitted")


def backup_db() -> Path:
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True, parents=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    dest = out_dir / f"applications.backup-retired-remediation-{ts}.db"
    shutil.copy2(DB_PATH, dest)
    return dest


def _read_letter(rel_path: str | None) -> str:
    if not rel_path:
        return ""
    full = ROOT / rel_path
    if not full.exists():
        return ""
    try:
        return full.read_text(encoding="utf-8")
    except OSError:
        return ""


def scan(conn) -> dict:
    """Read-only. Returns {'mutable': [...], 'report_only': [...]} — each entry a dict
    with url/company/title/status/cover_letter_path/retired (sorted list of names found)."""
    rows = conn.execute(
        "SELECT url, company, title, status, cover_letter_path FROM jobs "
        "WHERE cover_letter_path IS NOT NULL AND cover_letter_path != ''"
    ).fetchall()
    mutable, report_only = [], []
    for row in rows:
        text = _read_letter(row["cover_letter_path"])
        retired = find_retired_project_mentions(text)
        if not retired:
            continue
        entry = {
            "url": row["url"], "company": row["company"], "title": row["title"],
            "status": row["status"], "cover_letter_path": row["cover_letter_path"],
            "retired": retired,
        }
        if row["status"] in REPORT_ONLY_STATUSES:
            report_only.append(entry)
        elif row["status"] in MUTABLE_STATUSES:
            mutable.append(entry)
        # else: status not in either set — left untouched and unreported (see docstring).
    return {"mutable": mutable, "report_only": report_only}


def apply_remediation(conn, mutable: list) -> None:
    conn.executemany(
        "UPDATE jobs SET cover_letter_path = NULL, status = 'scored' WHERE url = :url",
        [{"url": e["url"]} for e in mutable],
    )
    conn.commit()


def _print_entries(label: str, entries: list) -> None:
    print(f"\n[remediate] {label}: {len(entries)}")
    for e in entries[:20]:
        print(f"  [{e['status']}] {e['company']} — {e['title']} | retired: {', '.join(e['retired'])} | {e['url']}")
    if len(entries) > 20:
        print(f"  ... and {len(entries) - 20} more")


def main(dry_run: bool = False) -> None:
    init_db()
    conn = get_conn()

    result = scan(conn)
    mutable, report_only = result["mutable"], result["report_only"]

    print(f"[remediate] {len(mutable)} row(s) will be reset to status='scored' "
          f"(cover_letter_path cleared) for regeneration.")
    print(f"[remediate] {len(report_only)} row(s) contain retired-project text but are "
          f"submission_unconfirmed/submitted — NEVER auto-modified; reported for human review.")
    _print_entries("Rows to remediate", mutable)
    _print_entries("Rows for manual review only (not touched)", report_only)

    status_breakdown = Counter(e["status"] for e in mutable)
    print(f"\n[remediate] By status: {dict(status_breakdown)}")

    if dry_run:
        print("\n[remediate] --dry-run active: no backup taken, no rows written.")
        conn.close()
        return

    if not mutable:
        print("\n[remediate] Nothing to remediate.")
        conn.close()
        return

    backup_path = backup_db()
    print(f"\n[remediate] Backed up DB to {backup_path}")
    apply_remediation(conn, mutable)
    print(f"[remediate] Reset {len(mutable)} row(s) to status='scored'.")
    conn.close()
    print("\n[remediate] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="One-time remediation of cached cover letters mentioning a retired "
                    "project. Run ONLY inside the maintenance freeze (see module docstring)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
