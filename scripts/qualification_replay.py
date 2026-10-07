#!/usr/bin/env python3
"""
scripts/qualification_replay.py — READ-ONLY replay of the qualification engine over stored jobs.

Never writes to the database (opened with a `mode=ro` URI). Writes one JSON line per job and
prints a transition matrix (old outcome x new decision).

Usage:
    python scripts/qualification_replay.py --db db/applications.db \
        --statuses filtered,scored,tailored,submitted,manual_review --out replay.jsonl
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from filters import assess  # noqa: E402

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
DECISIONS = ("qualified", "review", "rejected")
ROLE_REASON_MARKERS = ("excluded_role", "too_senior", "stack_mismatch", "seniority", "qualification")


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the database read-only; any write attempt raises sqlite3.OperationalError."""
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_jobs(conn: sqlite3.Connection, statuses: list[str]) -> list[sqlite3.Row]:
    marks = ",".join("?" for _ in statuses)
    return conn.execute(
        "SELECT id, url, title, status, status_reason, tier, required_years, description "
        f"FROM jobs WHERE status IN ({marks}) ORDER BY id", statuses).fetchall()


def old_outcome(row: sqlite3.Row) -> str:
    """Old status; 'filtered' is split into role/qualification rejections vs other gates."""
    if row["status"] != "filtered":
        return row["status"]
    reason = row["status_reason"] or ""
    is_role = any(marker in reason for marker in ROLE_REASON_MARKERS)
    return "filtered:role" if is_role else "filtered:other(location/salary/..)"


def replay_row(row: sqlite3.Row, cfg: dict) -> dict:
    qual = assess(row["title"] or "", row["description"] or "", cfg)
    return {
        "id": row["id"], "url": row["url"], "title": row["title"], "old_status": row["status"],
        "old_reason": row["status_reason"], "old_tier": row["tier"],
        "new_decision": qual.decision, "new_tier": qual.tier, "confidence": qual.confidence,
        "fit_score": qual.fit_score, "required_years": qual.required_years,
        "reasons": list(qual.reasons),
    }


def format_matrix(matrix: Counter) -> str:
    olds = sorted({old for old, _ in matrix})
    width = max(len(o) for o in olds) + 2
    lines = [f"{'old outcome':<{width}}" + "".join(f"{d:>11}" for d in DECISIONS) + f"{'total':>9}"]
    for old in olds:
        counts = [matrix[(old, d)] for d in DECISIONS]
        lines.append(f"{old:<{width}}" + "".join(f"{n:>11}" for n in counts) + f"{sum(counts):>9}")
    totals = [sum(matrix[(o, d)] for o in olds) for d in DECISIONS]
    lines.append(f"{'TOTAL':<{width}}" + "".join(f"{n:>11}" for n in totals) + f"{sum(totals):>9}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only qualification replay.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--statuses", default="filtered,scored,tailored,submitted,manual_review")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    conn = open_readonly(args.db)
    rows = load_jobs(conn, [s.strip() for s in args.statuses.split(",") if s.strip()])
    matrix: Counter = Counter()
    with args.out.open("w") as out:
        for row in rows:
            record = replay_row(row, cfg)
            out.write(json.dumps(record) + "\n")
            matrix[(old_outcome(row), record["new_decision"])] += 1
    conn.close()
    print(f"[replay] {len(rows)} jobs -> {args.out}\n")
    print(format_matrix(matrix))


if __name__ == "__main__":
    main()
