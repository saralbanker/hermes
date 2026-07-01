"""
tracker.py — CLI dashboard for tracking the Hermes application pipeline.

Usage:
    python src/tracker.py stats
    python src/tracker.py list [--status STATUS] [--today] [--limit N]
    python src/tracker.py export [--output FILE]
"""

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent))
from db import (  # noqa: E402
    avg_score,
    count_today,
    get_conn,
    get_daily_counts,
    init_db,
    status_counts,
)

console = Console()

# All canonical statuses in display order
STATUS_ORDER = [
    "discovered",
    "scored",
    "tailored",
    "applying",
    "submitted",
    "confirmed",
    "error",
]

# Rich colour map by status
STATUS_COLOURS = {
    "confirmed":  "green",
    "submitted":  "yellow",
    "tailored":   "yellow",
    "applying":   "cyan",
    "scored":     "blue",
    "discovered": "white",
    "error":      "red",
}


# ---------------------------------------------------------------------------
# Helper — coloured status cell
# ---------------------------------------------------------------------------

def _status_markup(status: str | None) -> str:
    colour = STATUS_COLOURS.get(str(status or ""), "white")
    return f"[{colour}]{status or '—'}[/{colour}]"


def _score_markup(score) -> str:
    if score is None:
        return "—"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return str(score)
    if s >= 8:
        return f"[green]{s:.1f}[/green]"
    if s >= 7:
        return f"[yellow]{s:.1f}[/yellow]"
    return f"[red]{s:.1f}[/red]"


# ---------------------------------------------------------------------------
# cmd_stats
# ---------------------------------------------------------------------------

def cmd_stats():
    """Print two rich tables: status breakdown + pipeline summary."""
    init_db()

    counts = status_counts()         # {"discovered": 164, ...}
    daily  = get_daily_counts()      # {"linkedin_count": 12, "other_count": 19, "total_count": 31}
    avg    = avg_score()             # float or None

    # Today's per-status counts require per-status applied_at filtering.
    # We use a single query: count rows created today per status.
    conn = get_conn()
    today_str = date.today().isoformat()
    today_rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM jobs "
        "WHERE DATE(created_at) = ? GROUP BY status",
        (today_str,),
    ).fetchall()
    conn.close()
    today_counts = {r["status"]: r["cnt"] for r in today_rows}

    # ── Table 1: Status breakdown ──────────────────────────────────────────
    t1 = Table(title="Hermes — Application Stats", show_lines=True)
    t1.add_column("Status",    style="bold", min_width=14)
    t1.add_column("Total",     justify="right", min_width=8)
    t1.add_column("Today",     justify="right", min_width=8)

    for status in STATUS_ORDER:
        total = counts.get(status, 0)
        today = today_counts.get(status, 0)
        colour = STATUS_COLOURS.get(status, "white")
        t1.add_row(
            f"[{colour}]{status}[/{colour}]",
            str(total),
            str(today),
        )

    console.print(t1)

    # ── Table 2: Pipeline summary ──────────────────────────────────────────
    from rich.table import Table as RichTable

    linkedin_used  = daily.get("linkedin_count", 0)
    other_used     = daily.get("other_count", 0)
    total_applied  = counts.get("confirmed", 0) + counts.get("submitted", 0)

    t2 = RichTable(title="Pipeline Summary", show_lines=True)
    t2.add_column("Metric",  style="bold", min_width=20)
    t2.add_column("Value",   justify="right", min_width=14)

    t2.add_row("LinkedIn used / limit",  f"{linkedin_used} / 15")
    t2.add_row("Other used / limit",     f"{other_used} / 30")
    t2.add_row("Avg score",              str(avg) if avg is not None else "—")
    t2.add_row("Total applied",          str(total_applied))

    console.print(t2)


# ---------------------------------------------------------------------------
# cmd_list
# ---------------------------------------------------------------------------

def cmd_list(status: str | None = None, today_only: bool = False, limit: int = 20):
    """Print a rich table of jobs filtered by status / date."""
    init_db()

    conn = get_conn()
    query = "SELECT * FROM jobs"
    conditions: list[str] = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if today_only:
        conditions.append("DATE(applied_at) = ?")
        params.append(date.today().isoformat())

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY score DESC NULLS LAST, created_at DESC"
    query += f" LIMIT {int(limit)}"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    t = Table(title="Job Applications", show_lines=True)
    t.add_column("#",        justify="right",  style="dim",   min_width=3)
    t.add_column("Company",  min_width=16)
    t.add_column("Title",    min_width=24)
    t.add_column("Score",    justify="right",  min_width=6)
    t.add_column("Status",   min_width=11)
    t.add_column("Board",    min_width=10)
    t.add_column("Applied",  min_width=12)

    for i, row in enumerate(rows, 1):
        # Applied column: human-friendly relative time or ISO datetime
        applied_raw = row["applied_at"]
        if applied_raw:
            try:
                applied_dt = datetime.fromisoformat(applied_raw)
                delta = datetime.utcnow() - applied_dt
                hours = int(delta.total_seconds() // 3600)
                if hours < 1:
                    applied_str = "< 1h ago"
                elif hours < 24:
                    applied_str = f"{hours}h ago"
                else:
                    applied_str = applied_dt.strftime("%Y-%m-%d")
            except ValueError:
                applied_str = applied_raw
        else:
            applied_str = "—"

        t.add_row(
            str(i),
            str(row["company"] or "—"),
            str(row["title"] or "—"),
            _score_markup(row["score"]),
            _status_markup(row["status"]),
            str(row["job_board"] or "—"),
            applied_str,
        )

    console.print(t)
    console.print(f"[dim]{len(rows)} job(s) shown[/dim]")


# ---------------------------------------------------------------------------
# cmd_export
# ---------------------------------------------------------------------------

def cmd_export(output_path: str = "applications.csv"):
    """Export all jobs to a CSV file."""
    init_db()

    conn = get_conn()
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No jobs in DB to export.[/yellow]")
        return

    fieldnames = list(rows[0].keys())

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    console.print(f"[green]Exported {len(rows)} jobs to {out}[/green]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    init_db()

    parser = argparse.ArgumentParser(
        description="Hermes job tracker CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # stats
    sub.add_parser("stats", help="Show application pipeline statistics.")

    # list
    p_list = sub.add_parser("list", help="List jobs with optional filters.")
    p_list.add_argument("--status", default=None, help="Filter by status.")
    p_list.add_argument("--today",  action="store_true", help="Show only today's jobs.")
    p_list.add_argument("--limit",  type=int, default=20, help="Max rows to show.")

    # export
    p_export = sub.add_parser("export", help="Export all jobs to CSV.")
    p_export.add_argument(
        "--output", default="applications.csv", metavar="FILE",
        help="Output CSV file path (default: applications.csv).",
    )

    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats()
    elif args.command == "list":
        cmd_list(status=args.status, today_only=args.today, limit=args.limit)
    elif args.command == "export":
        cmd_export(output_path=args.output)


if __name__ == "__main__":
    main()
