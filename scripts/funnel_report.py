#!/usr/bin/env python3
"""Read-only outcome funnel: interviews per 100 applications by qualification decision.

Population: jobs with status in ('submitted', 'submission_unconfirmed').

Stages (cumulative where noted):
  applied      every application in the group
  response     any email correlated to the job (response_status set)
  engagement   non-ack, non-rejection reply (includes interview invites)
  interview    response_status == 'positive'
  rejection    response_status == 'rejection'
  no_signal    nothing correlated

NOT OBSERVABLE: application views. No view/open events are captured by any
current source (Gmail/IMAP watcher only sees replies), so there is no "viewed"
stage. Applications younger than 14 days are too young to judge; they are
counted and reported but still included in group rates.

Groups: qual_version, qual_decision, tier, confidence band, applied week.
The qual_* columns may not exist yet; they are then reported as "unknown".
The DB is opened with sqlite3 URI mode=ro; nothing is ever written.

Usage: python scripts/funnel_report.py [--db PATH] [--since YYYY-MM-DD] [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "db" / "applications.db"
APPLIED_STATUSES = ("submitted", "submission_unconfirmed")
MIN_SAMPLE = 30
YOUNG_DAYS = 14
UNKNOWN = "unknown"
STAGES = ("response", "engagement", "interview", "rejection", "no_signal")
DIMENSIONS = ("qual_version", "qual_decision", "tier", "confidence_band", "applied_week")


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the database strictly read-only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def confidence_band(value: float | None) -> str:
    """Bucket a qualification confidence into <0.5, 0.5-0.75, >=0.75."""
    if value is None:
        return UNKNOWN
    if value < 0.5:
        return "<0.5"
    return "0.5-0.75" if value < 0.75 else ">=0.75"


def parse_applied_at(raw: str | None) -> datetime | None:
    """Parse an ISO applied_at value; None if missing or malformed."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def applied_week(moment: datetime | None) -> str:
    """ISO week label like 2026-W27, or unknown."""
    if moment is None:
        return UNKNOWN
    year, week, _ = moment.isocalendar()
    return f"{year}-W{week:02d}"


def load_applications(conn: sqlite3.Connection, since: str | None) -> list[sqlite3.Row]:
    """Fetch applications, selecting qual_* columns only if they exist."""
    present = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    optional = [c for c in ("qual_version", "qual_decision", "qual_confidence") if c in present]
    cols = ["id", "tier", "applied_at", "response_status"] + optional
    marks = ",".join("?" for _ in APPLIED_STATUSES)
    sql = f"SELECT {', '.join(cols)} FROM jobs WHERE status IN ({marks})"
    params: list[str] = list(APPLIED_STATUSES)
    if since:
        sql += " AND applied_at >= ?"
        params.append(since)
    return conn.execute(sql, params).fetchall()


def _value(row: sqlite3.Row, key: str) -> object:
    return row[key] if key in row.keys() else None


def stage_flags(response_status: str | None) -> dict[str, bool]:
    """Map a job's response_status to funnel stage membership."""
    status = (response_status or "").strip().lower()
    return {
        "response": bool(status),
        "engagement": bool(status) and status not in ("ack", "rejection"),
        "interview": status == "positive",
        "rejection": status == "rejection",
        "no_signal": not status,
    }


def describe(row: sqlite3.Row, now: datetime) -> dict[str, object]:
    """Flatten one application row into dimension values, stage flags and age."""
    moment = parse_applied_at(row["applied_at"])
    is_young = moment is None or (now - moment) < timedelta(days=YOUNG_DAYS)
    return {
        "qual_version": _value(row, "qual_version") or UNKNOWN,
        "qual_decision": _value(row, "qual_decision") or UNKNOWN,
        "tier": row["tier"] or UNKNOWN,
        "confidence_band": confidence_band(_value(row, "qual_confidence")),
        "applied_week": applied_week(moment),
        "is_young": is_young,
        "flags": stage_flags(row["response_status"]),
    }


def _empty_bucket() -> dict[str, int]:
    return {"n": 0, "young": 0, **{s: 0 for s in STAGES}}


def aggregate(applications: list[dict[str, object]]) -> dict[str, dict[str, dict[str, int]]]:
    """Count stages per value for each grouping dimension."""
    result: dict[str, dict[str, dict[str, int]]] = {d: {} for d in DIMENSIONS}
    result["overall"] = {"all": _empty_bucket()}
    for app in applications:
        targets = [result["overall"]["all"]]
        for dim in DIMENSIONS:
            targets.append(result[dim].setdefault(str(app[dim]), _empty_bucket()))
        for bucket in targets:
            bucket["n"] += 1
            bucket["young"] += int(bool(app["is_young"]))
            for stage in STAGES:
                bucket[stage] += int(app["flags"][stage])  # type: ignore[index]
    return result


def rates(bucket: dict[str, int]) -> dict[str, object]:
    """Per-100 rates, or an INSUFFICIENT SAMPLE marker when n < MIN_SAMPLE."""
    if bucket["n"] < MIN_SAMPLE:
        return {"status": "INSUFFICIENT SAMPLE"}
    return {"status": "ok", **{s: round(100 * bucket[s] / bucket["n"], 1) for s in STAGES}}


def build_report(applications: list[dict[str, object]]) -> dict[str, object]:
    """Assemble counts, rates and young-application coverage."""
    grouped = aggregate(applications)
    report: dict[str, object] = {"min_sample": MIN_SAMPLE, "young_days": YOUNG_DAYS}
    for dim, groups in grouped.items():
        report[dim] = {
            key: {"counts": bucket, "per_100": rates(bucket)}
            for key, bucket in sorted(groups.items())
        }
    return report


def format_group(key: str, entry: dict[str, dict[str, object]]) -> str:
    """One text line for a group."""
    counts, per_100 = entry["counts"], entry["per_100"]
    head = f"  {key:<14} n={counts['n']:<4} young(<{YOUNG_DAYS}d)={counts['young']:<4}"
    raw = " ".join(f"{s}={counts[s]}" for s in STAGES)
    if per_100["status"] != "ok":
        return f"{head} {raw} | per100: INSUFFICIENT SAMPLE (n<{MIN_SAMPLE})"
    pct = " ".join(f"{s}={per_100[s]}" for s in STAGES)
    return f"{head} {raw} | per100: {pct}"


def format_text(report: dict[str, object]) -> str:
    """Render the report as plain text."""
    overall = report["overall"]["all"]  # type: ignore[index]
    counts = overall["counts"]
    lines = [
        f"FUNNEL (applications: {counts['n']}; <{YOUNG_DAYS}d old, too young to judge: "
        f"{counts['young']}; matured: {counts['n'] - counts['young']})",
        "Application views: NOT OBSERVABLE (no view events captured).",
        format_group("overall", overall),
    ]
    for dim in DIMENSIONS:
        lines.append(f"\nBy {dim}:")
        lines.extend(format_group(k, v) for k, v in report[dim].items())  # type: ignore[union-attr]
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only interview funnel report.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--since", help="only applications with applied_at >= YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def run(db_path: Path, since: str | None, as_json: bool, now: datetime | None = None) -> str:
    """Produce the report text (or JSON) for a database."""
    conn = open_readonly(db_path)
    try:
        rows = load_applications(conn, since)
    finally:
        conn.close()
    moment = now or datetime.now()
    report = build_report([describe(r, moment) for r in rows])
    return json.dumps(report, indent=2) if as_json else format_text(report)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    print(run(args.db, args.since, args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
