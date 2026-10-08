"""Read-only query layer for the Hermes dashboard.

Uses only the legacy `jobs` table. Every function takes an open read-only
connection (see open_readonly) and returns plain JSON-serialisable data.
No paths, descriptions, cover letters or profile data ever leave this module.
"""
from __future__ import annotations

import fcntl
import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Statuses that are NOT failures (happy path, deliberate terminal, or in-flight).
NON_FAILURE_STATES = (
    "submitted", "already_applied", "filtered", "skipped", "expired",
    "scored", "tailored", "discovered", "applying", "dry_run_ok", "cap_reached",
)
RESPONSE_BUCKETS = ("positive", "ack", "rejection", "other")
REASON_MAX = 120
PREFIX_MAX = 60
LOG_TAIL_LINES = 15
TAIL_READ_BYTES = 16 * 1024
_NOT_FAILURE_SQL = ",".join("?" for _ in NON_FAILURE_STATES)
_CHANNEL = "COALESCE(apply_channel, job_board)"


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the DB read-only; any write raises sqlite3.OperationalError."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _clean_reason(text: str | None, limit: int = REASON_MAX) -> str:
    """Collapse whitespace to a single line and truncate (reasons may hold page dumps)."""
    return " ".join((text or "").split())[:limit]


def _reason_prefix(text: str | None) -> str:
    return " ".join((text or "").split(":", 1)[0].split())[:PREFIX_MAX]


def _last_n_days(today: str, days: int = 14) -> list[str]:
    end = date.fromisoformat(today)
    return [(end - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def get_applications(conn: sqlite3.Connection, today: str, limit: int) -> dict:
    """Submitted counts: today, cap usage, total and the 14-day series."""
    days = _last_n_days(today)
    rows = conn.execute(
        "SELECT substr(applied_at,1,10) AS d, COUNT(*) AS n FROM jobs "
        "WHERE status='submitted' AND substr(applied_at,1,10) BETWEEN ? AND ? GROUP BY d",
        (days[0], days[-1]),
    ).fetchall()
    by_day = {r["d"]: r["n"] for r in rows}
    total = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='submitted'").fetchone()[0]
    used = by_day.get(today, 0)
    return {
        "submitted_today": used,
        "cap": {"used": used, "limit": limit, "remaining": max(0, limit - used)},
        "submitted_total": total,
        "last_14_days": [{"date": d, "count": by_day.get(d, 0)} for d in days],
    }


def get_breakdowns(conn: sqlite3.Connection) -> dict:
    """Submitted rows grouped by channel, tier and resume variant."""
    exprs = {
        "by_channel": _CHANNEL,
        "by_tier": "COALESCE(tier,'core')",
        "by_variant": "COALESCE(resume_variant,'unknown')",
    }
    out: dict = {}
    for key, expr in exprs.items():
        rows = conn.execute(
            f"SELECT {expr} AS name, COUNT(*) AS n FROM jobs "  # expr is a constant above
            "WHERE status='submitted' GROUP BY 1 ORDER BY 2 DESC, 1"
        ).fetchall()
        out[key] = [{"name": r["name"], "count": r["n"]} for r in rows]
    return out


def get_responses(conn: sqlite3.Connection) -> dict:
    """Employer response buckets over submitted rows, awaiting count and rate."""
    rows = conn.execute(
        "SELECT response_status AS s, COUNT(*) AS n FROM jobs "
        "WHERE status='submitted' GROUP BY 1"
    ).fetchall()
    counts = dict.fromkeys(RESPONSE_BUCKETS, 0)
    awaiting = 0
    for r in rows:
        if r["s"] is None:
            awaiting += r["n"]
        else:
            counts[r["s"] if r["s"] in counts else "other"] += r["n"]
    submitted = awaiting + sum(counts.values())
    rate = (submitted - awaiting) / submitted if submitted else 0.0
    return {"counts": counts, "awaiting": awaiting, "response_rate": rate}


def get_errors(conn: sqlite3.Connection, today: str) -> dict:
    """Failures grouped by last attempt (there is no per-day failure history)."""
    base = (f"FROM jobs WHERE status NOT IN ({_NOT_FAILURE_SQL}) "
            "AND last_attempt_at IS NOT NULL ")
    excl = NON_FAILURE_STATES
    today_rows = conn.execute(
        f"SELECT status, COUNT(*) AS n {base} AND substr(last_attempt_at,1,10)=? "
        "GROUP BY status ORDER BY n DESC, status", (*excl, today)).fetchall()
    since = _last_n_days(today, 7)[0]
    week_rows = conn.execute(
        f"SELECT status, status_reason {base} AND substr(last_attempt_at,1,10)>=?",
        (*excl, since)).fetchall()
    groups: dict[tuple[str, str], int] = {}
    for r in week_rows:
        key = (r["status"], _reason_prefix(r["status_reason"]))
        groups[key] = groups.get(key, 0) + 1
    top = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    recent = conn.execute(
        f"SELECT company, title, status, substr(status_reason,1,2000) AS reason, "
        f"last_attempt_at {base} ORDER BY last_attempt_at DESC LIMIT 10", excl).fetchall()
    return {
        "today_total": sum(r["n"] for r in today_rows),
        "today_by_status": [{"status": r["status"], "count": r["n"]} for r in today_rows],
        "top_groups_7d": [{"status": s, "reason_prefix": p, "count": n} for (s, p), n in top],
        "recent": [{"company": r["company"], "title": r["title"], "status": r["status"],
                    "reason": _clean_reason(r["reason"]), "at": r["last_attempt_at"]}
                   for r in recent],
    }


def get_pipeline_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY 1 ORDER BY 2 DESC").fetchall()
    return {"status_counts": {r["status"]: r["n"] for r in rows}}


def is_lock_held(lock_path: Path) -> bool:
    """True if another process holds the run lock (non-blocking probe, released at once)."""
    try:
        fd = open(lock_path, "rb")  # read-only: never creates or modifies the file
    except FileNotFoundError:
        return False  # no lock file means no run has ever started
    except OSError:
        logger.exception("lock probe: cannot open %s", lock_path)
        return False
    with fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        except OSError:
            logger.exception("lock probe: flock failed on %s", lock_path)
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False


def _read_tail_bytes(path: Path, size: int = TAIL_READ_BYTES) -> bytes | None:
    """Last `size` bytes of a file, or None if it does not exist yet."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - size))
            return fh.read()
    except FileNotFoundError:
        return None  # file not created yet: caller reports "no data"


def _read_last_run(metrics_path: Path) -> dict | None:
    data = _read_tail_bytes(metrics_path, 64 * 1024)
    if not data:
        return None
    lines = [ln for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
    try:
        rec = json.loads(lines[-1])
    except (json.JSONDecodeError, IndexError):
        logger.warning("metrics.jsonl: last line is not valid JSON")
        return None
    return {"at": rec.get("at"), "total_s": rec.get("total_s"),
            "status_counts": rec.get("status_counts", {})}


def read_run_state(repo_root: Path) -> dict:
    """Running flag, last run metrics and the tail of the cron log."""
    out = repo_root / "output"
    data = _read_tail_bytes(out / "hermes_cron.log")
    lines = data.decode("utf-8", "replace").splitlines() if data else []
    return {
        "is_running": is_lock_held(out / "hermes.lock"),
        "last_run": _read_last_run(out / "metrics.jsonl"),
        "log_tail": [_clean_reason(ln, 300) for ln in lines[-LOG_TAIL_LINES:]],
    }


def read_limits(repo_root: Path) -> dict:
    """Whitelisted config view: limits, search.min_score, salary. Never profile/answers."""
    with open(repo_root / "config.yaml") as fh:
        cfg = yaml.safe_load(fh) or {}
    return {
        "limits": dict(cfg.get("limits") or {}),
        "min_score": (cfg.get("search") or {}).get("min_score"),
        "salary": dict(cfg.get("salary") or {}),
    }


def build_overview(conn: sqlite3.Connection, today: str, repo_root: Path) -> dict:
    """Assemble the single /api/overview payload."""
    settings = read_limits(repo_root)
    limit = int(settings["limits"].get("total_per_day", 0))
    apps = get_applications(conn, today, limit)
    apps.update(get_breakdowns(conn))
    return {
        "today": today,
        "run": read_run_state(repo_root),
        "applications": apps,
        "responses": get_responses(conn),
        "errors": get_errors(conn, today),
        "pipeline": get_pipeline_counts(conn),
        "settings": settings,
    }
