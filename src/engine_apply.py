"""
src/engine_apply.py — Phase 3: the Indeed channel hardened onto src/engine/.

PARALLEL, OPT-IN path. Nothing in src/apply.py, scripts/run_hermes.sh, or any
systemd unit imports or calls this module. It is reachable only by a direct,
deliberate call (e.g. from a script or a REPL), and even then it refuses to
run unless config.yaml's `engine.enabled` is true (see EngineDisabledError
below) — two independent gates between "this code exists" and "this code can
submit a real application."

What this replaces (when explicitly invoked): instead of src/apply.py's
record_result() writing ad hoc `jobs` table columns (status, status_reason,
attempts, submission_evidence, screenshot_path), the claim/outcome/channel-
health bookkeeping goes through src/engine/claim.py (atomic claim + lease +
fencing), src/engine/transitions.py (the §68 Transition Table, execution_phase
boundaries), and src/engine/channel_health.py (DATA_MODEL §8 / BROWSER_SYSTEM
§103/§103.1) against the v2 schema from db/migrations/0001_opportunity_model.sql.

The actual browser automation is untouched: this module calls
indeed_apply.run_indeed_apply() exactly as src/apply.py does, with one
addition — an on_progress callback (added to indeed_apply.py as a purely
additive, default-None parameter; see that file's docstrings on
run_indeed_apply/_click_next_or_submit) that writes execution_phase
synchronously at the two boundaries BROWSER_SYSTEM.md §70/§72 define.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import yaml

import states as S
from submission_gate import run_submission_gate
from engine import channel_health as ch
from engine import claim, db as enginedb, transitions
from engine.enums import ChannelStatus, ExecutionPhase

ROOT = Path(__file__).parent.parent
INDEED_CHANNEL_KEY = "indeed"
WWR_CHANNEL_KEY = "wwr"
WELLFOUND_CHANNEL_KEY = "wellfound"
DEFAULT_LEASE_SECONDS = 15 * 60

# §103.1-derived cooldown durations. Like Phase 2's retry backoff, no doc
# specifies these numerically (the project's stated pattern defers non-
# correctness-critical numbers to measured host behavior); these are this
# implementation's chosen defaults, easy to retune once real data exists.
RATE_LIMIT_COOLDOWN_SECONDS = 30 * 60
NETWORK_COOLDOWN_SECONDS = 10 * 60
ANTIBOT_COOLDOWN_SECONDS = 24 * 60 * 60


class EngineDisabledError(RuntimeError):
    """Raised when the new path is invoked while config.yaml's `engine.enabled`
    is not true. This is a second, independent guard beyond "nothing on the
    scheduled path calls this module" — belt and suspenders for code that
    can submit real applications under the user's identity."""


def load_config() -> dict:
    return yaml.safe_load(open(ROOT / "config.yaml"))


def is_engine_enabled(cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else load_config()
    return bool((cfg.get("engine") or {}).get("enabled"))


def _require_enabled(cfg: dict | None) -> None:
    if not is_engine_enabled(cfg):
        raise EngineDisabledError(
            "config.yaml engine.enabled is false — refusing to run the Phase 3 "
            "Indeed integration. Flipping the flag is a deliberate, separate "
            "decision from building or testing this code; scripts/run_hermes.sh "
            "and every systemd unit never read this flag and are unaffected either way."
        )


# ---------------------------------------------------------------------------
# opportunity -> legacy job-dict shape (indeed_apply.py only reads url/
# company/title from it)
# ---------------------------------------------------------------------------

def _resolve_apply_url(conn: sqlite3.Connection, opportunity_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT source_url FROM source_observations
        WHERE opportunity_id = ? AND source_url IS NOT NULL AND source_url != ''
        ORDER BY observed_at DESC LIMIT 1
        """,
        (opportunity_id,),
    ).fetchone()
    return row["source_url"] if row else None


def _resolve_description(conn: sqlite3.Connection, opportunity_id: int) -> str:
    from engine import description_store

    row = conn.execute(
        "SELECT description_ref FROM source_observations WHERE opportunity_id = ? "
        "ORDER BY observed_at DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    return description_store.read(row["description_ref"] if row else None)


def _resolve_raw_metadata(conn: sqlite3.Connection, opportunity_id: int) -> str | None:
    """The most recent source_observations.raw_metadata — Phase 7 only (Indeed never sets
    this column, so this is a no-op addition for apply_indeed_via_engine). Carries forward
    whatever ats_meta src/sources_wwr.py found inline in the listing's RSS description at
    discovery time (a direct Greenhouse/Lever link), so apply_wwr_via_engine's route
    resolution can skip redirect_resolver entirely when it is already known."""
    row = conn.execute(
        "SELECT raw_metadata FROM source_observations WHERE opportunity_id = ? "
        "AND raw_metadata IS NOT NULL AND raw_metadata != '' ORDER BY observed_at DESC LIMIT 1",
        (opportunity_id,),
    ).fetchone()
    return row["raw_metadata"] if row else None


def _opportunity_to_job_dict(conn: sqlite3.Connection, opp: sqlite3.Row) -> dict:
    return {
        "url": _resolve_apply_url(conn, opp["opportunity_id"]),
        "company": opp["company_display"] or opp["company_normalized"],
        "title": opp["job_title_display"] or opp["job_title_normalized"],
        "description": _resolve_description(conn, opp["opportunity_id"]),
        "location": opp["location_display"] or opp["location_normalized"],
        "ats_meta": _resolve_raw_metadata(conn, opp["opportunity_id"]),
    }


# ---------------------------------------------------------------------------
# Tailoring (WORKFLOW_ENGINE.md §47: CLAIM -> TAILOR -> RESOLVE CHANNEL -> APPLY)
# ---------------------------------------------------------------------------

def _tailor(conn: sqlite3.Connection, claimed: claim.ClaimResult, job: dict, now: str):
    """Returns (cover_letter, None) on success, or (None, TransitionResult)
    on an AI failure that must short-circuit the caller — reusing Phase 4's
    failure bridge (src/engine/ai/failure.py), which itself reuses Phase 2's
    record_tailoring_failure: execution_phase is still NOT_STARTED here (no
    browser action has begun), so this never consumes a MAX_ATTEMPTS slot."""
    from engine.ai import generate
    from engine.ai.failure import release_on_ai_failure

    try:
        variant = generate.select_resume_variant(job["title"] or "", job.get("description") or "")
        result = generate.generate_cover_letter(job, [], variant)
        return result.letter, None
    except Exception as exc:  # AIUnavailable/AITimeout and any other tailoring exception alike
        return None, release_on_ai_failure(conn, claimed.attempt_id, claimed.opportunity_id, exc, now)


# ---------------------------------------------------------------------------
# execution_phase progress callback — wired into indeed_apply.run_indeed_apply
# ---------------------------------------------------------------------------

def _make_progress_writer(conn: sqlite3.Connection, attempt_id: int):
    def on_progress(marker: str) -> None:
        if marker == "external_work_started":
            transitions.mark_external_work_started(conn, attempt_id)
        elif marker == "submit_intent":
            transitions.mark_submit_intent(conn, attempt_id)
    return on_progress


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def apply_indeed_via_engine(
    conn: sqlite3.Connection,
    worker_id: str,
    cover_letter: str | None,
    resume_path: str,
    screenshot_dir: str,
    *,
    dry_run: bool = False,
    cfg: dict | None = None,
    now: str | None = None,
):
    """Claim the next Indeed-eligible opportunity (if any) and drive it
    through the hardened flow. Returns None if nothing was claimed, else the
    terminal TransitionResult from whichever transitions.record_* function
    matched the outcome.

    `cover_letter=None` (the worker's normal call shape, WORKFLOW_ENGINE.md
    §47's CLAIM -> TAILOR -> RESOLVE CHANNEL -> APPLY order): a real cover
    letter is generated here, after claiming, via src/engine/ai/generate.py
    (Phase 4). Passing an explicit string (Phase 3's original call shape,
    still used by its own tests) skips generation entirely — unchanged
    behavior for every existing caller.

    Raises EngineDisabledError unless config.yaml's engine.enabled is true.
    """
    _require_enabled(cfg)
    now = now or enginedb.now_iso()

    claimed = claim.claim_next(
        conn, worker_id, DEFAULT_LEASE_SECONDS, now, channel_filter=INDEED_CHANNEL_KEY
    )
    if claimed is None:
        return None

    opp = enginedb.fetch_opportunity(conn, claimed.opportunity_id)
    job = _opportunity_to_job_dict(conn, opp)
    early_exit = _claim_preconditions(conn, claimed, job, now)
    if early_exit is not None:
        return early_exit

    if cover_letter is None:
        cover_letter, tailor_failure = _tailor(conn, claimed, job, now)
        if tailor_failure is not None:
            return tailor_failure

    return _drive_and_record(conn, claimed, job, cover_letter, resume_path, screenshot_dir, dry_run, now)


def apply_wwr_via_engine(
    conn: sqlite3.Connection,
    worker_id: str,
    cover_letter: str | None,
    resume_path: str,
    screenshot_dir: str,
    *,
    dry_run: bool = False,
    cfg: dict | None = None,
    now: str | None = None,
):
    """Phase 7 — the We Work Remotely channel hardened onto src/engine/. Thin wrapper
    around the shared redirect-sourced-channel driver (_apply_redirect_channel_via_engine,
    see that function's docstring for the full CLAIM -> TAILOR -> RESOLVE CHANNEL -> APPLY
    behavior); the only WWR-specific thing left here is the channel key itself
    (`channel_filter="wwr"`, see WWR_CHANNEL_KEY), so claim.claim_next only picks up
    WWR-origin opportunities (tagged "wwr" at discovery by src/engine/discovery.py's
    _SOURCE_LEVEL_CHANNEL) and every outcome below is recorded against the dedicated "wwr"
    channel_health row.

    Same `cover_letter=None` call-shape convention as apply_indeed_via_engine. Raises
    EngineDisabledError unless config.yaml's engine.enabled is true.
    """
    return _apply_redirect_channel_via_engine(
        conn, worker_id, cover_letter, resume_path, screenshot_dir, WWR_CHANNEL_KEY,
        dry_run=dry_run, cfg=cfg, now=now,
    )


def apply_wellfound_via_engine(
    conn: sqlite3.Connection,
    worker_id: str,
    cover_letter: str | None,
    resume_path: str,
    screenshot_dir: str,
    *,
    dry_run: bool = False,
    cfg: dict | None = None,
    now: str | None = None,
):
    """Phase 8 (IMPLEMENTATION_ROADMAP.md §82) — Wellfound, hardened onto src/engine/ the
    same way Phase 7 did for WWR: both are "redirect-sourced" channels whose real
    application destination is unknown at claim time, so they share
    _apply_redirect_channel_via_engine wholesale (channel_filter="wellfound" is the only
    difference). See that function's docstring for the full behavior, and
    _resolve_redirect_route's `direct_apply_only` branch for the Wellfound-specific finding
    this phase's discovery investigation produced: most/all live Wellfound postings observed
    (src/sources_wellfound.py's public JSON-LD read, directApply:true on every sample) have
    no external employer apply route at all — the only "Apply" action is Wellfound's own
    authenticated one-click flow, which this project will not log into or automate (no stored
    Wellfound credentials exist in this repo; IMPLEMENTATION_ROADMAP.md §82/§84: no bypass).
    Those opportunities resolve straight to UNSUPPORTED_CHANNEL with zero browser navigation
    toward wellfound.com at apply time. A Wellfound posting that DOES carry an inline
    Greenhouse/Lever link, or any posting discovered with directApply:false (none observed
    live during this phase, but the code does not assume there are none), is driven exactly
    like a WWR redirect: via the shared redirect_resolver / ats_apply / direct_form path.

    Same `cover_letter=None` call-shape convention as apply_indeed_via_engine. Raises
    EngineDisabledError unless config.yaml's engine.enabled is true.
    """
    return _apply_redirect_channel_via_engine(
        conn, worker_id, cover_letter, resume_path, screenshot_dir, WELLFOUND_CHANNEL_KEY,
        dry_run=dry_run, cfg=cfg, now=now,
    )


def _apply_redirect_channel_via_engine(
    conn: sqlite3.Connection,
    worker_id: str,
    cover_letter: str | None,
    resume_path: str,
    screenshot_dir: str,
    channel: str,
    *,
    dry_run: bool = False,
    cfg: dict | None = None,
    now: str | None = None,
):
    """Shared CLAIM -> TAILOR -> RESOLVE CHANNEL -> APPLY driver (WORKFLOW_ENGINE.md §47)
    for any "redirect-sourced" channel — one whose real application destination is not
    known at claim time, unlike Indeed's fixed route. Extracted during Phase 8 per the
    Phase 7 report's explicit recommendation ("near-identical for any future redirect-sourced
    channel... reuse, don't duplicate") once Wellfound needed the exact same shape WWR
    already had: both `apply_wwr_via_engine` and `apply_wellfound_via_engine` are now thin
    callers of this function, parameterized only by `channel`.

    WORKFLOW_ENGINE.md §47's RESOLVE CHANNEL step happens here, between TAILOR and APPLY,
    using either an inline ATS link the discovery source already found
    (job["ats_meta"], see _resolve_raw_metadata) or redirect_resolver.resolve_apply_target —
    the same shared resolver src/apply.py's CH_REDIRECT handling uses for Himalayas/
    Remotive/RemoteOK/WWR (see _resolve_redirect_route). The resolved destination is then
    driven by src/ats_apply.py (Greenhouse/Lever) or src/direct_form.py (any other employer
    form) exactly as src/apply.py's route() does, reused unmodified except for their new
    additive on_progress parameter. Ashby is refused outright (BLOCKED_ANTIBOT) — the same
    platform-wide block src/apply.py's route() hardcodes (IMPLEMENTATION_ROADMAP.md §85:
    "Ashby is not a bypass project").

    `channel_filter=channel` (passed to claim.claim_next below) restricts claiming to that
    channel's own discovery-tagged opportunities (work_queue.candidate_channel, set at
    discovery time by src/engine/discovery.py's _SOURCE_LEVEL_CHANNEL — not the resolved
    execution channel) — so every outcome-recording call below (_record_outcome and its
    helpers, reused unchanged from the Indeed path via claimed.channel) always writes
    channel_health against that channel's own dedicated row, never against the shared
    greenhouse/lever/ashby rows other sources' resolved routes also use
    (IMPLEMENTATION_ROADMAP.md §85: "do not modify their existing ... channel-health
    handling").
    """
    _require_enabled(cfg)
    now = now or enginedb.now_iso()

    claimed = claim.claim_next(
        conn, worker_id, DEFAULT_LEASE_SECONDS, now, channel_filter=channel
    )
    if claimed is None:
        return None

    opp = enginedb.fetch_opportunity(conn, claimed.opportunity_id)
    job = _opportunity_to_job_dict(conn, opp)
    early_exit = _claim_preconditions(conn, claimed, job, now)
    if early_exit is not None:
        return early_exit

    if cover_letter is None:
        cover_letter, tailor_failure = _tailor(conn, claimed, job, now)
        if tailor_failure is not None:
            return tailor_failure

    execution_channel, blocked = _resolve_redirect_route(job)
    if blocked is not None:
        # Route resolution itself failed before any form-page navigation began —
        # execution_phase is still NOT_STARTED, so _record_outcome's existing
        # not-started handling (reused unchanged below) releases this without consuming
        # an attempt where that handling applies (e.g. a resolver browser/network hiccup);
        # a genuine finding about the opportunity itself (unsupported destination) is
        # recorded as such regardless.
        return _record_outcome(conn, claimed, blocked, now)
    transitions.resolve_channel(conn, claimed.attempt_id, execution_channel, now)

    return _drive_redirect_channel_and_record(
        conn, claimed, job, execution_channel, cover_letter, resume_path, screenshot_dir, dry_run, now
    )


def _resolve_redirect_route(job: dict) -> tuple[str | None, S.ApplyResult | None]:
    """WORKFLOW_ENGINE.md §47 RESOLVE CHANNEL step for a redirect-sourced job (WWR or
    Wellfound). Mirrors src/apply.py's resolve_channel()/_follow_redirect() for its
    CH_REDIRECT case, reusing the same shared redirect_resolver.resolve_apply_target (never
    reimplemented here) rather than rebuilding route resolution. Two deliberate differences
    from apply.py's own glue code, both there to stay correct without touching apply.py (out
    of scope):

      1. No `jobs`-table persistence of the resolved route — an engine claim is a single
         attempt's unit of work; re-resolving on a later attempt is cheap browser/HTTP
         work, not a correctness problem.
      2. Reads the resolver's own "channel" key directly, rather than re-deriving the ATS
         name from ats_meta["ats"] the way apply.py's _apply_resolved_target does — that
         re-derivation assumes every non-None ats_meta carries an "ats" key, which
         redirect_resolver.resolve_fast_http's own WWR fast-path branch does not guarantee
         for a bare employer destination (its ats_meta there is only
         {"direct_apply_url": ...}, no "ats" key) — apply.py's own _apply_resolved_target
         would raise KeyError on that exact shape; this function does not replicate that.

    Returns (execution_channel, None) with job["ats_meta"] / job["direct_apply_url"] set as
    ats_apply.run_ats_apply / direct_form.run_direct_apply respectively need, or
    (None, ApplyResult) for a terminal pre-navigation outcome.
    """
    if job.get("ats_meta"):
        meta = json.loads(job["ats_meta"])
        if meta.get("ats") in S.ATS_CHANNELS:
            return meta["ats"], None
        if meta.get("direct_apply_only"):
            # Phase 8 finding (src/sources_wellfound.py, verified live against real
            # wellfound.com postings): a listing whose own public JSON-LD already told us,
            # at discovery time, that it carries no external employer apply route — its
            # "Apply" action is the source platform's own authenticated flow (Wellfound's
            # one-click apply). No credentials for that platform exist anywhere in this
            # repo (checked: config.yaml, env, output/hermes.env) and this project will not
            # log in or bypass that wall (IMPLEMENTATION_ROADMAP.md §82/§84, ARCHITECTURE_
            # REDESIGN_FINAL §18.2 forbidden assumption). Recorded as NO_SUPPORTED_ROUTE with
            # zero browser navigation toward the source platform's own apply surface —
            # strictly safer than even attempting resolve_apply_target, which would have to
            # navigate there to find out the same thing.
            return None, S.ApplyResult(S.UNSUPPORTED_CHANNEL,
                                       "platform_internal_apply_only: no external employer route")

    from redirect_resolver import resolve_apply_target
    target = resolve_apply_target(job["url"])

    if target.get("channel") and target.get("ats_meta"):
        job["ats_meta"] = target["ats_meta"]
        if target["channel"] == S.CH_DIRECT:
            job["direct_apply_url"] = (
                json.loads(target["ats_meta"]).get("direct_apply_url") or target.get("final_url")
            )
        return target["channel"], None

    err = str(target.get("error") or "")
    if err.startswith("unsupported_destination") and target.get("final_url"):
        # A real employer form, just not one of the known ATS platforms — hand off to the
        # generic direct-form engine instead of giving up (same handoff apply.py's
        # _apply_resolved_target makes for this exact error prefix).
        job["direct_apply_url"] = target["final_url"]
        job["ats_meta"] = json.dumps({"direct_apply_url": target["final_url"]})
        return S.CH_DIRECT, None
    if not err:
        err = "no employer apply target found"
    if err.startswith("blocked_antibot:"):
        return None, S.ApplyResult(S.BLOCKED_ANTIBOT, f"redirect: {err}")
    state = S.UNSUPPORTED_CHANNEL if err.startswith(("unsupported", "account_required", "sponsored_link")) \
        else S.NETWORK_ERROR
    return None, S.ApplyResult(state, f"redirect: {err}")


def _drive_redirect_channel_and_record(conn: sqlite3.Connection, claimed: claim.ClaimResult, job: dict,
                          execution_channel: str, cover_letter: str, resume_path: str,
                          screenshot_dir: str, dry_run: bool, now: str):
    """Shared APPLY + record step for any redirect-sourced channel (WWR, Wellfound, ...)
    once _resolve_redirect_route has produced a real execution_channel. `claimed.channel`
    (the discovery-tagged source channel, e.g. "wwr"/"wellfound") names the screenshot file
    and is what every channel_health write below is keyed on — `execution_channel` is only
    used to pick the driver (ats_apply vs direct_form) and is never itself written to
    channel_health here."""
    # Gate first — after route resolution, before any run_*_apply and before the Ashby
    # refusal — so a bad-data job is a terminal VALIDATION_FAILED, never mis-booked as an
    # anti-bot block against channel health.
    blocked = _gate_or_record_block(conn, claimed, job, cover_letter, now)
    if blocked is not None:
        return blocked
    if execution_channel == S.CH_ASHBY:
        # Same platform-wide anti-bot refusal src/apply.py's route() hardcodes for Ashby
        # (IMPLEMENTATION_ROADMAP.md §85: "Ashby is not a bypass project") — a deliberate
        # pre-navigation refusal, so no browser work happens and no attempt is consumed
        # beyond the usual BLOCKED_ANTIBOT -> channel_blocked bookkeeping.
        result = S.ApplyResult(S.BLOCKED_ANTIBOT,
                               "ashby disabled: platform anti-bot blocks automated submissions")
        return _record_outcome(conn, claimed, result, now)

    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
    screenshot_path = str(Path(screenshot_dir) / f"{claimed.attempt_id}_{claimed.channel}.png")
    on_progress = _make_progress_writer(conn, claimed.attempt_id)

    # Same per-job LLM-answer context src/apply.py's route() sets before calling
    # ats_apply.py/direct_form.py (answers.answer_question reads it via a module-level
    # global, not a parameter) — without this, open-ended question answers would be
    # generated against whatever job a previous call last set, or no context at all.
    from answers import set_job_context
    set_job_context(job["company"], job["title"], job.get("description") or "", job.get("location") or "")

    if execution_channel in S.ATS_CHANNELS:
        from ats_apply import run_ats_apply
        result = run_ats_apply(job, cover_letter, resume_path, screenshot_path,
                               dry_run=dry_run, on_progress=on_progress)
    else:
        from direct_form import run_direct_apply
        result = run_direct_apply(job, cover_letter, resume_path, screenshot_path,
                                  dry_run=dry_run, on_progress=on_progress)
    return _record_outcome(conn, claimed, result, now)


def _claim_preconditions(conn: sqlite3.Connection, claimed: claim.ClaimResult, job: dict, now: str):
    if not job["url"]:
        # No source observation carries a usable URL — cannot even navigate.
        # No external work began; release without consuming an attempt.
        return transitions.record_tailoring_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, now=now,
            reason="no_source_url_for_opportunity",
        )
    return None


def _gate_or_record_block(conn: sqlite3.Connection, claimed: claim.ClaimResult, job: dict,
                          cover_letter: str | None, now: str):
    """Hard pre-submission gate (src/submission_gate.py::run_submission_gate — the same
    single fail-closed entry point src/apply.py uses). Returns None when the job is clean;
    otherwise records a terminal VALIDATION_FAILED outcome (execution_phase is still
    NOT_STARTED: no external work has begun) and returns its TransitionResult. Callers
    MUST return that result without calling any run_*_apply function."""
    findings = run_submission_gate(job, cover_letter)
    if not findings:
        return None
    result = S.ApplyResult(S.VALIDATION_FAILED, "; ".join(findings)[:400])
    return _record_outcome(conn, claimed, result, now)


def _drive_and_record(conn: sqlite3.Connection, claimed: claim.ClaimResult, job: dict,
                       cover_letter: str, resume_path: str, screenshot_dir: str,
                       dry_run: bool, now: str):
    blocked = _gate_or_record_block(conn, claimed, job, cover_letter, now)
    if blocked is not None:
        return blocked
    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
    screenshot_path = str(Path(screenshot_dir) / f"{claimed.attempt_id}_indeed.png")
    on_progress = _make_progress_writer(conn, claimed.attempt_id)

    from indeed_apply import run_indeed_apply

    result = run_indeed_apply(
        job, cover_letter, resume_path, screenshot_path, dry_run=dry_run, on_progress=on_progress
    )
    return _record_outcome(conn, claimed, result, now)


# ---------------------------------------------------------------------------
# Outcome mapping: legacy states.ApplyResult -> engine transitions
# ---------------------------------------------------------------------------

def _has_alternate_route(conn: sqlite3.Connection, opportunity_id: int, blocked_channel: str) -> bool:
    """Whether any OTHER channel is currently HEALTHY — crude but correct
    per WORKFLOW_ENGINE.md §106/§107: a block on one route is not evidence
    another route is unusable. Full per-opportunity route enumeration is
    Browser-System/channel-resolution territory beyond this phase's scope
    (see Phase 2 report's channel-resolution simplification note)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM channel_health WHERE channel_key != ? AND status = 'HEALTHY'",
        (blocked_channel,),
    ).fetchone()
    return row["n"] > 0


def _bump_form_failure_streak(conn: sqlite3.Connection, channel_key: str, now: str) -> int:
    conn.execute(
        "UPDATE channel_health SET failure_streak = failure_streak + 1, "
        "last_error_class = 'form_changed', last_failure_at = ?, updated_at = ? WHERE channel_key = ?",
        (now, now, channel_key),
    )
    row = enginedb.fetch_channel_health(conn, channel_key)
    return row["failure_streak"] if row else 0


def _record_outcome(conn: sqlite3.Connection, claimed: claim.ClaimResult, result, now: str):
    """Maps one indeed_apply.ApplyResult onto the correct engine transition
    + channel_health write. See BROWSER_SYSTEM.md §68 Error Taxonomy /
    §103 Channel Health Feedback for the outcome -> channel-health mapping,
    and DATA_MODEL.md §7.4 for the 7-value attempt-outcome enum this all
    ultimately funnels into."""
    attempt = enginedb.fetch_attempt(conn, claimed.attempt_id)
    phase = ExecutionPhase(attempt["execution_phase"])
    not_started = phase is ExecutionPhase.NOT_STARTED

    if result.state in (S.SUBMITTED, S.ALREADY_APPLIED):
        return _record_confirmed(conn, claimed, result, now)

    simple = _record_simple_outcome(conn, claimed, result.state, phase, now)
    if simple is not _NO_MATCH:
        return simple

    if result.state == S.VALIDATION_FAILED:
        return _record_validation_failed(conn, claimed, result, phase, now)

    if result.state == S.LOGIN_REQUIRED:
        return _record_login_required(conn, claimed, not_started, now)

    # S.BLOCKED_ANTIBOT (Phase 7 — indeed_apply.run_indeed_apply never returns this state, so
    # Phase 3's dispatch never needed it; ats_apply.py/direct_form.py's bot-risk-rejection
    # classification, and src/apply.py's own hardcoded Ashby block, both do) is the same
    # BROWSER_SYSTEM.md §103 anti-bot signal as a security interstitial/captcha — CHANNEL_
    # BLOCKED outcome + channel_health.ANTIBOT_BLOCKED, same as those two states already get.
    if result.state in (S.SECURITY_INTERSTITIAL, S.CAPTCHA_REQUIRED, S.BLOCKED_ANTIBOT):
        return _record_security_block(conn, claimed, now)

    if result.state == S.FORM_CHANGED:
        return _record_form_changed(conn, claimed, now)

    if result.state == S.OTP_REQUIRED:
        return transitions.record_retryable_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, claimed.attempt_number,
            error_code="otp_required", error_class=None, now=now,
        )

    if result.state in (S.NETWORK_ERROR, S.FAILED):
        return _record_infra_or_fatal(conn, claimed, result, not_started, phase, now)

    if result.state == S.DRY_RUN_OK:
        return transitions.record_tailoring_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, now=now, reason="dry_run_ok"
        )

    # Never silently drop an unmapped legacy state (SYSTEM_RULES: no silent
    # failure) — fail closed into MANUAL_REVIEW rather than leave the lease
    # dangling.
    return transitions.record_terminal_failure(
        conn, claimed.attempt_id, claimed.opportunity_id, execution_phase=phase,
        error_class=f"unmapped_state:{result.state}", now=now,
    )


_NO_MATCH = object()


def _record_simple_outcome(conn: sqlite3.Connection, claimed: claim.ClaimResult, state: str,
                            phase: ExecutionPhase, now: str):
    """The three outcomes that map to exactly one transitions.* call with no
    extra channel_health or streak bookkeeping. Returns _NO_MATCH when
    `state` is none of these, so the caller falls through to the branches
    that need more than a single dispatched call."""
    if state == S.SUBMISSION_UNCONFIRMED:
        return transitions.record_submission_unconfirmed(conn, claimed.attempt_id, claimed.opportunity_id, now=now)
    if state == S.EXPIRED:
        return transitions.record_posting_expired(
            conn, claimed.attempt_id, claimed.opportunity_id, execution_phase=phase, now=now
        )
    if state == S.UNSUPPORTED_CHANNEL:
        return transitions.record_unsupported_channel(conn, claimed.attempt_id, claimed.opportunity_id, now=now)
    return _NO_MATCH


def _record_validation_failed(conn: sqlite3.Connection, claimed: claim.ClaimResult, result,
                               phase: ExecutionPhase, now: str):
    """Pre-submission gate block (src/submission_gate.py): a data problem that needs a
    human fix — terminal (MANUAL_REVIEW), never retried, and no channel_health effect
    (the channel itself is fine). The finding text is kept in error_code for triage."""
    return transitions.record_terminal_failure(
        conn, claimed.attempt_id, claimed.opportunity_id, execution_phase=phase,
        error_class="validation_failed", error_code=(result.detail or "")[:200], now=now,
    )


def _record_confirmed(conn: sqlite3.Connection, claimed: claim.ClaimResult, result, now: str):
    """SUBMITTED and ALREADY_APPLIED both land on transitions that promote
    the opportunity to COMPLETED and both are evidence the channel itself
    is working (DATA_MODEL.md §12.3: ALREADY_APPLIED counts 0 toward the
    daily cap, but it still proves Indeed accepted/recognized the
    interaction — a healthy-channel signal, per WORKFLOW_ENGINE.md §61's own
    example of what counts as routine/healthy)."""
    if result.state == S.SUBMITTED:
        tr = transitions.record_submitted(
            conn, claimed.attempt_id, claimed.opportunity_id, claimed.channel,
            confirmation_text=result.evidence, now=now,
        )
    else:
        tr = transitions.record_already_applied(conn, claimed.attempt_id, claimed.opportunity_id, now=now)
    ch.record_success(conn, claimed.channel, now)
    return tr


def _record_login_required(conn: sqlite3.Connection, claimed: claim.ClaimResult, not_started: bool, now: str):
    """BROWSER_SYSTEM.md §103: login_required -> channel_health.status =
    AUTH_EXPIRED. If the session check (which runs before job-page
    navigation) is what failed, execution_phase is still NOT_STARTED — no
    external work toward *this* opportunity began, so release it rather
    than consuming an attempt (the channel-wide AUTH_EXPIRED degrade is
    what actually protects the system: claim.py's route-usability check
    already stops any further Indeed claims until §103.1's re-auth clears it)."""
    ch.degrade(conn, claimed.channel, ChannelStatus.AUTH_EXPIRED, error_class="login_required", now=now)
    if not_started:
        return transitions.record_tailoring_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, now=now, reason="auth_expired_pre_navigation"
        )
    return transitions.record_retryable_failure(
        conn, claimed.attempt_id, claimed.opportunity_id, claimed.attempt_number,
        error_code="login_required", error_class="authentication_expired", now=now,
    )


def _record_security_block(conn: sqlite3.Connection, claimed: claim.ClaimResult, now: str):
    """BROWSER_SYSTEM.md §103/§112: a Cloudflare interstitial that never
    cleared, or a CAPTCHA, is a security block — no bypass, ever. Attempt
    outcome CHANNEL_BLOCKED, channel_health.status = ANTIBOT_BLOCKED
    (Patch 7's two-field pattern), minimum cooldown applied per §103.1
    (an explicit confirm_probe_succeeded call is required later — a timer
    alone never clears ANTIBOT_BLOCKED)."""
    ch.degrade(
        conn, claimed.channel, ChannelStatus.ANTIBOT_BLOCKED,
        cooldown_seconds=ANTIBOT_COOLDOWN_SECONDS, error_class="anti_bot_block", now=now,
    )
    has_alt = _has_alternate_route(conn, claimed.opportunity_id, claimed.channel)
    return transitions.record_channel_blocked(
        conn, claimed.attempt_id, claimed.opportunity_id, claimed.channel,
        has_alternate_route=has_alt, now=now,
    )


def _record_form_changed(conn: sqlite3.Connection, claimed: claim.ClaimResult, now: str):
    """BROWSER_SYSTEM.md §103: 'repeated form schema failures ->
    FORM_SCHEMA_CHANGED' — a single occurrence is a bounded-reinspection
    retryable failure at the attempt level; only a streak degrades the
    whole channel (ch.FORM_SCHEMA_FAILURE_STREAK_THRESHOLD)."""
    streak = _bump_form_failure_streak(conn, claimed.channel, now)
    if streak >= ch.FORM_SCHEMA_FAILURE_STREAK_THRESHOLD:
        ch.degrade(conn, claimed.channel, ChannelStatus.FORM_SCHEMA_CHANGED,
                   error_class="form_changed", now=now)
    return transitions.record_retryable_failure(
        conn, claimed.attempt_id, claimed.opportunity_id, claimed.attempt_number,
        error_code="form_changed", error_class="form_changed", now=now,
    )


def _record_infra_or_fatal(conn: sqlite3.Connection, claimed: claim.ClaimResult, result,
                            not_started: bool, phase: ExecutionPhase, now: str):
    """BROWSER_SYSTEM.md §69/§71 Infrastructure Failure / Crash Before
    Submit: if execution_phase never left NOT_STARTED, no external work
    toward this opportunity began — release without consuming an attempt,
    regardless of whether the legacy state is NETWORK_ERROR or FAILED."""
    if not_started:
        return transitions.record_tailoring_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, now=now,
            reason=f"infra_failure_pre_navigation:{result.state}",
        )
    if result.state == S.NETWORK_ERROR:
        ch.degrade(
            conn, claimed.channel, ChannelStatus.NETWORK_UNAVAILABLE,
            cooldown_seconds=NETWORK_COOLDOWN_SECONDS,
            error_class="network_timeout_before_external_action", now=now,
        )
        return transitions.record_retryable_failure(
            conn, claimed.attempt_id, claimed.opportunity_id, claimed.attempt_number,
            error_code="network_error", error_class="network_timeout_before_external_action", now=now,
        )
    return transitions.record_terminal_failure(
        conn, claimed.attempt_id, claimed.opportunity_id, execution_phase=phase,
        error_class="fatal_error", error_code=result.state, now=now,
    )
