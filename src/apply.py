"""
apply.py — The application engine: pick tailored jobs, route each to its applier,
and record the result as an explicit state transition (see states.py).

    tailored ──claim──▶ applying ──applier──▶ submitted | <failure state>
                                           └─ retryable failure ─▶ tailored (attempts < MAX)

Order of work:
  1. Queue = tailored jobs, core and stretch allocated to ~70/30 of today's plan.
  2. Per job: duplicate check → atomic claim → route by channel → ApplyResult.
  3. Only a confirmation page (ApplyResult.evidence) counts as submitted.
Submissions are serial: one browser, one account, human-paced delays.

CLI:
  python src/apply.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import states as S
from cap_enforcer import remaining_today
from db import (already_applied_key, claim_job, dedupe_key, get_conn, get_jobs_by_status,
                increment_daily, init_db, tier_counts_today, update_job)
from filters import role_priority

ROOT = Path(__file__).parent.parent
SCREENSHOTS = ROOT / "screenshots"
REDIRECT_BOARDS = {"remotive", "himalayas", "remoteok"}


def load_config() -> dict:
    return yaml.safe_load(open(ROOT / "config.yaml"))


# ---------------------------------------------------------------------------
# Queue selection: core/stretch allocation
# ---------------------------------------------------------------------------

def _rank_key(job: dict) -> tuple:
    return (role_priority(job["title"] or "", job["description"] or ""), job["score"] or 0)


def build_queue(jobs: list[dict], cfg: dict, remaining: int, done: dict[str, int]) -> list[dict]:
    """Order jobs so today's submissions end up ~(1-share) core / share stretch.

    The stretch budget is a share of today's *planned* total, so a thin day never
    gets padded with stretch jobs, and a thin core supply is not filled beyond it.
    """
    search = cfg["search"]
    share = float(search.get("stretch_share", 0.3))
    core = sorted((j for j in jobs if (j.get("tier") or S.CORE) == S.CORE), key=_rank_key, reverse=True)
    stretch = sorted((j for j in jobs if j.get("tier") == S.STRETCH
                      and (j["score"] or 0) >= search.get("stretch_min_score", 7.5)),
                     key=_rank_key, reverse=True)
    done_total = sum(done.values())
    planned = done_total + min(remaining, len(core) + len(stretch))
    stretch_budget = max(0, math.floor(share * planned + 0.5) - done.get(S.STRETCH, 0))
    stretch = stretch[:stretch_budget]
    queue, ci, si = [], 0, 0
    # Interleave: take a stretch job whenever the running stretch share is below target.
    while len(queue) < remaining and (ci < len(core) or si < len(stretch)):
        n_stretch = done.get(S.STRETCH, 0) + si
        want_stretch = n_stretch < share * (done_total + len(queue) + 1)
        if si < len(stretch) and (want_stretch or ci >= len(core)):
            queue.append(stretch[si]); si += 1
        else:
            queue.append(core[ci]); ci += 1
    return queue


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def resolve_channel(job: dict) -> str:
    if job.get("apply_channel"):
        return job["apply_channel"]
    board = (job.get("job_board") or "").lower()
    if job.get("ats_meta"):
        return json.loads(job["ats_meta"]).get("ats", S.CH_REDIRECT)
    if board == "indeed":
        return S.CH_INDEED
    if board in REDIRECT_BOARDS:
        return S.CH_REDIRECT
    return ""


def _follow_redirect(job: dict) -> S.ApplyResult | None:
    """Resolve a board listing to its ATS. Returns a terminal result, or None when resolved."""
    from redirect_resolver import resolve_apply_target
    target = resolve_apply_target(job["url"])
    if target.get("error"):
        err = str(target["error"])
        state = S.UNSUPPORTED_CHANNEL if err.startswith("unsupported") else S.NETWORK_ERROR
        return S.ApplyResult(state, f"redirect: {err}")
    if not target.get("ats_meta"):
        return S.ApplyResult(S.UNSUPPORTED_CHANNEL, f"employer form: {target.get('final_url', '')[:200]}")
    meta = json.loads(target["ats_meta"])
    job["ats_meta"], job["apply_channel"] = target["ats_meta"], meta["ats"]
    update_job(job["url"], {"ats_meta": target["ats_meta"], "apply_channel": meta["ats"]})
    return None


def route(job: dict, cover: str, resume: str, shot: str, dry_run: bool) -> S.ApplyResult:
    from answers import set_job_context
    set_job_context(job["company"], job["title"], job.get("description") or "", job.get("location") or "")
    channel = resolve_channel(job)
    if channel == S.CH_REDIRECT:
        blocked = _follow_redirect(job)
        if blocked:
            return blocked
        channel = job["apply_channel"]
    if channel == S.CH_INDEED:
        from indeed_apply import run_indeed_apply
        return run_indeed_apply(job, cover, resume, shot, dry_run=dry_run)
    if channel in S.ATS_CHANNELS:
        from ats_apply import run_ats_apply
        return run_ats_apply(job, cover, resume, shot, dry_run=dry_run)
    return S.ApplyResult(S.UNSUPPORTED_CHANNEL, f"no applier for channel '{channel or job.get('job_board')}'")


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def record_result(job: dict, result: S.ApplyResult) -> str:
    """Persist an applier result. Returns the stored status."""
    url = job["url"]
    if result.state == S.SUBMITTED:
        update_job(url, {"status": S.SUBMITTED, "status_reason": None,
                         "applied_at": datetime.now().isoformat(timespec="seconds"),
                         "submission_evidence": (result.evidence or "")[:500],
                         "screenshot_path": result.screenshot})
        increment_daily("other")
        return S.SUBMITTED
    if result.state == S.DRY_RUN_OK:
        update_job(url, {"status": S.TAILORED, "status_reason": "dry_run_ok",
                         "attempts": max(0, (job.get("attempts") or 1) - 1)})  # a rehearsal is not an attempt
        return S.TAILORED
    attempts = job.get("attempts") or 0
    reason = f"{result.state}: {result.detail}"[:500]
    retry = result.state in S.RETRYABLE and attempts < S.MAX_ATTEMPTS
    status = S.TAILORED if retry else result.state
    update_job(url, {"status": status, "status_reason": reason,
                     "screenshot_path": result.screenshot})
    return status


def read_cover_letter(rel_path: str | None) -> str:
    full = ROOT / rel_path if rel_path else None
    return full.read_text().strip() if full and full.exists() else ""


def resolve_resume(variant: str | None, cfg: dict) -> str:
    resumes = cfg["resumes"]
    path = ROOT / (resumes.get(variant or "") or resumes["default"])
    return str(path if path.exists() else ROOT / resumes["default"])


def slug(job: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{job['company']}-{job['title']}".lower())[:60].strip("-")


def apply_one(job: dict, cfg: dict, dry_run: bool) -> S.ApplyResult | None:
    """Claim, apply, record. None when the job was skipped before any browser work."""
    key = job.get("dedupe_key") or dedupe_key(job["company"], job["title"])
    if already_applied_key(key, exclude_url=job["url"]):
        update_job(job["url"], {"status": S.SKIPPED, "status_reason": "duplicate_of_applied_role"})
        return None
    if not claim_job(job["url"]):
        return None  # another process took it
    job["attempts"] = (job.get("attempts") or 0) + 1
    SCREENSHOTS.mkdir(exist_ok=True)
    shot = str(SCREENSHOTS / f"{slug(job)}.png")
    cover = read_cover_letter(job.get("cover_letter_path"))
    try:
        result = route(job, cover, resolve_resume(job.get("resume_variant"), cfg), shot, dry_run)
    except Exception as exc:  # an applier bug must not kill the batch; recorded as FAILED
        result = S.ApplyResult(S.FAILED, f"{type(exc).__name__}: {exc}"[:400])
    record_result(job, result)
    return result


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def reset_stuck_applying(max_age_minutes: int = 0) -> int:
    """Rows left in 'applying' by a crashed run go back to the queue.

    Safe with age 0 because pipeline.py/run_hermes.sh hold the run lock, so no other
    applier can be mid-application. A standalone `apply.py` run uses 90 minutes.
    """
    conn = get_conn()
    cur = conn.execute(
        "UPDATE jobs SET status = 'tailored', status_reason = 'reset_after_crash' "
        "WHERE status = 'applying' AND (? = 0 OR last_attempt_at IS NULL OR "
        "last_attempt_at < datetime('now', ?))", (max_age_minutes, f"-{max_age_minutes} minutes"))
    conn.commit()
    conn.close()
    return cur.rowcount


class ChannelBreaker:
    """Stop using a channel for this run after a session/security problem."""

    def __init__(self) -> None:
        self.blocked: dict[str, str] = {}
        self.interstitials: dict[str, int] = {}

    def observe(self, channel: str, result: S.ApplyResult) -> None:
        if result.state == S.LOGIN_REQUIRED:
            self.blocked[channel] = "login_required"
            _notify_once("Hermes: Indeed login needed",
                         "Session expired. Run: python scripts/indeed_setup.py")
        elif result.state == S.SECURITY_INTERSTITIAL:
            self.interstitials[channel] = self.interstitials.get(channel, 0) + 1
            if self.interstitials[channel] >= 3:
                self.blocked[channel] = "repeated_security_interstitial"
        else:
            self.interstitials[channel] = 0


def _notify_once(title: str, body: str) -> None:
    try:
        from notify import notify
        notify(title, body, urgent=True)
    except Exception as exc:  # notification is best-effort; the log still records the cause
        print(f"  [apply] notify failed: {exc}")


def _print_result(i: int, total: int, job: dict, result: S.ApplyResult | None) -> None:
    state = result.state if result else "skipped"
    detail = (result.detail if result else "duplicate/claimed")[:110]
    mark = "✓" if state == S.SUBMITTED else ("·" if state == S.DRY_RUN_OK else "✗")
    print(f"  [apply] ({i}/{total}) {mark} {state:<22} [{job.get('tier') or 'core'}] "
          f"{job['company']} — {job['title']} | {detail}", flush=True)


def main(limit: int | None = None, dry_run: bool = False, max_minutes: int | None = None) -> dict:
    init_db()
    cfg = load_config()
    stuck = reset_stuck_applying(0 if os.environ.get("HERMES_LOCK_HELD") == "1" else 90)
    if stuck:
        print(f"[apply] Returned {stuck} job(s) stuck in 'applying' to the queue")
    remaining = remaining_today()["total_remaining"]
    if limit is not None:
        remaining = min(remaining, limit)
    jobs = [dict(j) for j in get_jobs_by_status(S.TAILORED)]
    queue = build_queue(jobs, cfg, remaining, tier_counts_today())
    budget = max_minutes or cfg["limits"].get("max_apply_minutes", 150)
    print(f"[apply] {len(jobs)} tailored, {remaining} slots left today → {len(queue)} queued "
          f"({sum(1 for j in queue if j.get('tier') == S.STRETCH)} stretch)"
          f"{' — DRY RUN, nothing is submitted' if dry_run else ''}; time budget {budget} min")
    return run_queue(queue, cfg, dry_run, deadline=time.time() + budget * 60)


def run_queue(queue: list[dict], cfg: dict, dry_run: bool, deadline: float) -> dict:
    stats: dict[str, int] = {}
    breaker = ChannelBreaker()
    for i, job in enumerate(queue, 1):
        if time.time() > deadline:
            print("[apply] Time budget used up; the rest waits for the next run.")
            break
        if not dry_run and remaining_today()["total_remaining"] == 0:
            print("[apply] Daily cap reached.")
            break
        channel = resolve_channel(job)
        if channel in breaker.blocked:
            continue
        t0 = time.time()
        result = apply_one(job, cfg, dry_run)
        _print_result(i, len(queue), job, result)
        if result is None:
            continue
        stats[result.state] = stats.get(result.state, 0) + 1
        stats["_seconds"] = stats.get("_seconds", 0) + int(time.time() - t0)
        breaker.observe(channel, result)
        if not dry_run and i < len(queue):
            lim = cfg["limits"]
            time.sleep(random.uniform(lim["min_delay_seconds"], lim["max_delay_seconds"]))
    if breaker.blocked:
        print(f"[apply] Channels paused this run: {breaker.blocked}")
    print(f"[apply] Done — {stats}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Submit tailored applications")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-minutes", type=int, default=None)
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run, max_minutes=args.max_minutes)
