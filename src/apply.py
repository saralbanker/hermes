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
from submission_gate import classify_gate_outcome, run_submission_gate

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
    core = sorted((j for j in jobs if (j.get("tier") or S.CORE) == S.CORE
                   and (j.get("attempts") or 0) < S.MAX_ATTEMPTS), key=_rank_key, reverse=True)
    stretch = sorted((j for j in jobs if j.get("tier") == S.STRETCH
                      and (j.get("attempts") or 0) < S.MAX_ATTEMPTS
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
        meta = json.loads(job["ats_meta"])
        if "direct_apply_url" in meta:
            return S.CH_DIRECT
        return meta.get("ats", S.CH_REDIRECT)
    if board == "indeed":
        return S.CH_INDEED
    if board in REDIRECT_BOARDS:
        return S.CH_REDIRECT
    return ""


def _apply_resolved_target(job: dict, target: dict, prefix: str) -> S.ApplyResult | None:
    """Common tail for _follow_redirect (aggregator boards) and _follow_indeed_external
    (Indeed's own 'Apply on company site' link): turn a redirect_resolver result into a
    channel, or a terminal failure. Returns None when job['apply_channel'] was set (the
    caller continues routing in the same call)."""
    if target.get("ats_meta"):
        meta = json.loads(target["ats_meta"])
        job["ats_meta"], job["apply_channel"] = target["ats_meta"], meta["ats"]
        update_job(job["url"], {"ats_meta": target["ats_meta"], "apply_channel": meta["ats"]})
        return None
    err = str(target.get("error") or "")
    final_url = target.get("final_url")
    if err.startswith("unsupported_destination") and final_url:
        # A real employer form, just not one of the known ATS platforms — hand off to the
        # generic direct-form engine instead of giving up. "account_required" (a board's
        # own signup wall, e.g. himalayas.app/signup/talent) is excluded on purpose: Hermes
        # never creates accounts, so there is nothing direct_form could do with it either.
        job["apply_channel"], job["direct_apply_url"] = S.CH_DIRECT, final_url
        # Persisted in ats_meta (reusing the existing JSON column, no schema change) so a
        # retry after a later failure still knows the resolved employer URL, not the
        # original listing/redirect.
        job["ats_meta"] = json.dumps({"direct_apply_url": final_url})
        update_job(job["url"], {"apply_channel": S.CH_DIRECT, "ats_meta": job["ats_meta"]})
        return None
    if not err:
        err = "no employer apply target found"
    state = S.UNSUPPORTED_CHANNEL if err.startswith(("unsupported", "account_required", "sponsored_link")) \
        else S.NETWORK_ERROR
    return S.ApplyResult(state, f"{prefix}: {err}")


def _follow_redirect(job: dict) -> S.ApplyResult | None:
    """Resolve a board listing to its ATS, or to the employer's own form for the generic
    direct_form engine. Returns a terminal result, or None when a channel was set."""
    from redirect_resolver import resolve_apply_target
    return _apply_resolved_target(job, resolve_apply_target(job["url"]), "redirect")


def _follow_indeed_external(job: dict, url: str) -> S.ApplyResult | None:
    """Indeed's own 'Apply on company site' link (applystart?jk=...): a browser hop, via
    redirect_resolver's dedicated profile (the target is the employer's own site, not
    Indeed, so the Indeed-authenticated session/profile is irrelevant here), to find the
    real form. Same classification and channel handoff as an aggregator redirect."""
    from redirect_resolver import resolve_indeed_external
    return _apply_resolved_target(job, resolve_indeed_external(url), "indeed external apply")


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
        result = run_indeed_apply(job, cover, resume, shot, dry_run=dry_run)
        external = (result.detail or "").removeprefix("external apply: ") \
            if result.state == S.UNSUPPORTED_CHANNEL and (result.detail or "").startswith("external apply:") \
            else None
        if not external:
            return result
        blocked = _follow_indeed_external(job, external.strip())
        if blocked:
            return blocked
        channel = job["apply_channel"]
    if channel in S.ATS_CHANNELS:
        if channel == S.CH_ASHBY:
            return S.ApplyResult(S.BLOCKED_ANTIBOT, "ashby disabled: platform anti-bot blocks automated submissions")
        from ats_apply import run_ats_apply
        return run_ats_apply(job, cover, resume, shot, dry_run=dry_run)
    if channel == S.CH_DIRECT:
        from direct_form import run_direct_apply
        if not job.get("direct_apply_url") and job.get("ats_meta"):
            job["direct_apply_url"] = json.loads(job["ats_meta"]).get("direct_apply_url")
        return run_direct_apply(job, cover, resume, shot, dry_run=dry_run)
    return S.ApplyResult(S.UNSUPPORTED_CHANNEL, f"no applier for channel '{channel or job.get('job_board')}'")


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

def is_infrastructure_failure(result: S.ApplyResult) -> bool:
    """Return True if failure occurred due to local Hermes/browser infrastructure
    before any external application work began (e.g. browser launch, Xvfb, local CDP)."""
    if result.state not in (S.NETWORK_ERROR, S.FAILED):
        return False
    detail = (result.detail or "").lower()
    infra_markers = (
        "browser launch failed",
        "browser connection fails",
        "browserconnecterror",
        "displayunavailable",
        "xvfb exited",
        "singletonlock",
        "failed to connect to the bus",
        "browser_error:browser.launch",
        "browser_error:target page, context or browser has been closed",
    )
    return any(marker in detail for marker in infra_markers)


def record_result(job: dict, result: S.ApplyResult) -> str:
    """Persist an applier result. Returns the stored status."""
    url = job["url"]
    if result.state == S.SUBMITTED:
        update_job(url, {"status": S.SUBMITTED, "status_reason": None,
                         "phase": S.PHASE_CONFIRMED,
                         "applied_at": datetime.now().isoformat(timespec="seconds"),
                         "submission_evidence": (result.evidence or "")[:500],
                         "screenshot_path": result.screenshot})
        increment_daily("other")
        return S.SUBMITTED
    if result.state == S.DRY_RUN_OK:
        update_job(url, {"status": S.TAILORED, "status_reason": "dry_run_ok",
                         "attempts": max(0, (job.get("attempts") or 1) - 1)})  # a rehearsal is not an attempt
        return S.TAILORED
    if is_infrastructure_failure(result):
        # Infrastructure failed before external application work began.
        # Do not consume a candidate application attempt.
        attempts = max(0, (job.get("attempts") or 1) - 1)
        job["attempts"] = attempts
        reason = f"infra_failure: {result.detail}"[:500]
        update_job(url, {"status": S.TAILORED, "status_reason": reason,
                         "attempts": attempts,
                         "screenshot_path": result.screenshot})
        return S.TAILORED
    if result.state == S.GATE_INFRA_ERROR:
        # The gate itself failed closed on an environment/config problem — not this job's
        # data. Revert the attempt (same treatment as any other infra failure) and leave
        # validation_attempts untouched; it will simply be retried on the next run.
        attempts = max(0, (job.get("attempts") or 1) - 1)
        update_job(url, {"status": S.TAILORED, "status_reason": f"gate_infra_error: {result.detail}"[:500],
                         "attempts": attempts, "screenshot_path": result.screenshot})
        return S.TAILORED
    if result.state == S.VALIDATION_FAILED:
        # A genuine gate finding or a job-data-specific gate exception — this job's data,
        # not the environment. Bounded by its own validation_attempts counter, separate
        # from the generic attempts/MAX_ATTEMPTS retry mechanism (see states.py).
        kind = (result.meta or {}).get("gate_kind", "finding")
        attempts = max(0, (job.get("attempts") or 1) - 1)
        validation_attempts = (job.get("validation_attempts") or 0) + 1
        exhausted = validation_attempts >= S.MAX_VALIDATION_ATTEMPTS
        status = S.MANUAL_REVIEW if exhausted else S.TAILORED
        update_job(url, {"status": status, "status_reason": f"{kind}: {result.detail}"[:500],
                         "attempts": attempts, "validation_attempts": validation_attempts,
                         "screenshot_path": result.screenshot})
        return status
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
    # Hard pre-submission gate: identity/placeholder/company checks on the cached cover
    # letter + identity payload about to reach a channel submitter. ANY failed check —
    # or any failure of the gate itself (it fails closed, never raises) — blocks dispatch
    # below: no warning mode, no soft fail.
    gate_findings = run_submission_gate(job, cover)
    gate_kind = classify_gate_outcome(gate_findings)
    if gate_kind == "infra_error":
        result = S.ApplyResult(S.GATE_INFRA_ERROR, "; ".join(gate_findings)[:400])
    elif gate_kind != "ok":
        result = S.ApplyResult(S.VALIDATION_FAILED, "; ".join(gate_findings)[:400], meta={"gate_kind": gate_kind})
    else:
        try:
            result = route(job, cover, resolve_resume(job.get("resume_variant"), cfg), shot, dry_run)
        except Exception as exc:  # an applier bug must not kill the batch
            from browser_watchdog import HardTimeoutError
            from db import get_job_phase
            if isinstance(exc, HardTimeoutError) or "timeout" in type(exc).__name__.lower():
                current_phase = get_job_phase(job["url"])
                if current_phase in (S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, S.PHASE_CONFIRMATION_PENDING):
                    result = S.ApplyResult(S.SUBMISSION_UNCONFIRMED, detail=f"timeout in submit phase: {exc}"[:400])
                elif current_phase == S.PHASE_CONFIRMED:
                    result = S.ApplyResult(S.SUBMITTED, evidence="submission confirmed prior to timeout")
                else:
                    result = S.ApplyResult(S.TIMEOUT, detail=f"pre-submit timeout: {exc}"[:400])
            else:
                result = S.ApplyResult(S.FAILED, f"{type(exc).__name__}: {exc}"[:400])
    record_result(job, result)
    return result


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def reset_stuck_applying(max_age_minutes: int = 0) -> int:
    """Rows left in 'applying' by a crashed run are recovered according to durable phase:
    1. SUBMIT_MAY_HAVE_DISPATCHED or CONFIRMATION_PENDING -> submission_unconfirmed (never automatically retry).
    2. CONFIRMED while in 'applying' -> invariant violation -> submission_unconfirmed.
    3. Missing / unknown phase -> fail closed as submission_unconfirmed (never infer 'not submitted').
    4. PRE_SUBMIT -> requeue to tailored if attempts < MAX_ATTEMPTS; otherwise fail.
    Returns count of rows requeued to tailored.
    """
    conn = get_conn()
    # 1. Submit-risk phases: commit happened before click or waiting confirmation. Never requeue.
    conn.execute(
        "UPDATE jobs SET status = 'submission_unconfirmed', "
        "status_reason = 'unconfirmed submission after crash in submit phase' "
        "WHERE status = 'applying' AND phase IN (?, ?) "
        "AND (? = 0 OR last_attempt_at IS NULL OR last_attempt_at < datetime('now', ?))",
        (S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, S.PHASE_CONFIRMATION_PENDING,
         max_age_minutes, f"-{max_age_minutes} minutes"),
    )
    # 2. Invariant violation: applying row with CONFIRMED phase. Fail closed for reconciliation.
    conn.execute(
        "UPDATE jobs SET status = 'submission_unconfirmed', "
        "status_reason = 'invariant violation: applying row with CONFIRMED phase' "
        "WHERE status = 'applying' AND phase = ? "
        "AND (? = 0 OR last_attempt_at IS NULL OR last_attempt_at < datetime('now', ?))",
        (S.PHASE_CONFIRMED, max_age_minutes, f"-{max_age_minutes} minutes"),
    )
    # 3. Missing/unknown phase on a stale applying row -> fail closed as submission_unconfirmed.
    conn.execute(
        "UPDATE jobs SET status = 'submission_unconfirmed', "
        "status_reason = 'unconfirmed submission: missing or unknown phase on crash recovery' "
        "WHERE status = 'applying' AND (phase IS NULL OR phase NOT IN (?, ?, ?, ?)) "
        "AND (? = 0 OR last_attempt_at IS NULL OR last_attempt_at < datetime('now', ?))",
        (S.PHASE_PRE_SUBMIT, S.PHASE_SUBMIT_MAY_HAVE_DISPATCHED, S.PHASE_CONFIRMATION_PENDING, S.PHASE_CONFIRMED,
         max_age_minutes, f"-{max_age_minutes} minutes"),
    )
    # 4. PRE_SUBMIT: safe to requeue if attempts remain; otherwise fail according to cap.
    conn.execute(
        "UPDATE jobs SET status = 'failed', status_reason = 'exceeded MAX_ATTEMPTS after crash' "
        "WHERE status = 'applying' AND phase = ? AND COALESCE(attempts, 0) >= ? "
        "AND (? = 0 OR last_attempt_at IS NULL OR last_attempt_at < datetime('now', ?))",
        (S.PHASE_PRE_SUBMIT, S.MAX_ATTEMPTS, max_age_minutes, f"-{max_age_minutes} minutes"),
    )
    cur = conn.execute(
        "UPDATE jobs SET status = 'tailored', status_reason = 'reset_after_crash' "
        "WHERE status = 'applying' AND phase = ? AND COALESCE(attempts, 0) < ? "
        "AND (? = 0 OR last_attempt_at IS NULL OR last_attempt_at < datetime('now', ?))",
        (S.PHASE_PRE_SUBMIT, S.MAX_ATTEMPTS, max_age_minutes, f"-{max_age_minutes} minutes"),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


class ChannelBreaker:
    """Stop using a channel for this run after a session/security problem."""

    def __init__(self) -> None:
        self.blocked: dict[str, str] = {}
        self.interstitials: dict[str, int] = {}
        self.antibot_hits: dict[str, int] = {}

    def observe(self, channel: str, result: S.ApplyResult) -> None:
        if result.state == S.LOGIN_REQUIRED:
            self.blocked[channel] = "login_required"
            _notify_once("Hermes: Indeed login needed",
                         "Session expired. Run: python scripts/indeed_setup.py")
        elif result.state == S.SECURITY_INTERSTITIAL:
            self.interstitials[channel] = self.interstitials.get(channel, 0) + 1
            if self.interstitials[channel] >= 3:
                self.blocked[channel] = "repeated_security_interstitial"
        elif result.state == S.BLOCKED_ANTIBOT:
            # A bot-risk rejection on one board is usually the ATS vendor's own shared
            # anti-spam system, not that one employer — two hits are enough to stop
            # burning the run's time budget on a channel that will keep rejecting us.
            self.antibot_hits[channel] = self.antibot_hits.get(channel, 0) + 1
            if self.antibot_hits[channel] >= 2:
                self.blocked[channel] = "repeated_antibot_block"
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
