"""
states.py — The single definition of Hermes job states and the applier result contract.

Every applier (indeed_apply, ats_apply, redirect) returns an ApplyResult; apply.py
is the only module that turns a result into a DB state transition. Nothing else
may invent state strings.

Lifecycle:
    discovered → filtered | scored → tailored → applying → submitted
                                                         ↘ <failure state>
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Happy path
DISCOVERED = "discovered"
FILTERED = "filtered"          # rejected by deterministic filters or similarity (terminal)
SCORED = "scored"
TAILORED = "tailored"          # ready to apply
APPLYING = "applying"          # claimed by a running applier
SUBMITTED = "submitted"        # confirmed by the ATS/Indeed success page (terminal)

# Failure / terminal states
SKIPPED = "skipped"                            # below score threshold, dedupe loser, etc.
EXPIRED = "expired"                            # posting closed or too old
INVALID = "invalid"                            # URL/meta unusable
CAP_REACHED = "cap_reached"                    # never stored: loop control only
LOGIN_REQUIRED = "login_required"              # session expired → user must re-login
SECURITY_INTERSTITIAL = "security_interstitial"  # Cloudflare / bot wall (retryable)
CAPTCHA_REQUIRED = "captcha_required"          # visible human-verification challenge blocks the form
BLOCKED_ANTIBOT = "blocked_antibot"            # invisible bot-risk check rejected the submission server-side
                                                # (e.g. reCAPTCHA Enterprise score, Ashby spam flag) — no
                                                # challenge to solve, and solving one is out of scope anyway;
                                                # not retried, since the same signal will recur.
OTP_REQUIRED = "otp_required"                  # phone OTP or unresolved email OTP
NETWORK_ERROR = "network_error"                # retryable
FORM_CHANGED = "form_changed"                  # form we cannot fill (unanswerable/unknown control)
ALREADY_APPLIED = "already_applied"            # terminal, counts as done (not toward today's cap)
SUBMISSION_UNCONFIRMED = "submission_unconfirmed"  # clicked submit, no success signal: never retried blindly
UNSUPPORTED_CHANNEL = "unsupported_channel"    # no applier for this destination (kept for future)
MODEL_UNAVAILABLE = "model_unavailable"
MODEL_TIMEOUT = "model_timeout"
FAILED = "failed"                              # unexpected error (retryable up to MAX_ATTEMPTS)
DRY_RUN_OK = "dry_run_ok"                      # form filled, submit deliberately skipped (never stored)
VALIDATION_FAILED = "validation_failed"        # pre-submission gate blocked it (terminal, not retryable:
                                                # a data problem, not a transient one — needs a human fix)

APPLIER_STATES = frozenset({
    SUBMITTED, EXPIRED, INVALID, LOGIN_REQUIRED, SECURITY_INTERSTITIAL, CAPTCHA_REQUIRED,
    BLOCKED_ANTIBOT, OTP_REQUIRED, NETWORK_ERROR, FORM_CHANGED, ALREADY_APPLIED,
    SUBMISSION_UNCONFIRMED, UNSUPPORTED_CHANNEL, FAILED, DRY_RUN_OK, VALIDATION_FAILED,
})

# States that go back to TAILORED for another attempt on a later run.
RETRYABLE = frozenset({SECURITY_INTERSTITIAL, NETWORK_ERROR, FAILED, LOGIN_REQUIRED,
                       OTP_REQUIRED, MODEL_UNAVAILABLE, MODEL_TIMEOUT})
MAX_ATTEMPTS = 3

# Channels (jobs.apply_channel)
CH_INDEED = "indeed"
CH_GREENHOUSE = "greenhouse"
CH_LEVER = "lever"
CH_ASHBY = "ashby"
CH_REDIRECT = "redirect"       # board listing whose Apply button leads elsewhere
CH_DIRECT = "direct"           # employer's own hand-rolled career-page form (direct_form.py)
ATS_CHANNELS = frozenset({CH_GREENHOUSE, CH_LEVER, CH_ASHBY})

# Tiers (jobs.tier)
CORE = "core"
STRETCH = "stretch"


@dataclass
class ApplyResult:
    state: str                         # one of APPLIER_STATES
    detail: str = ""                   # human-readable reason / error
    screenshot: str | None = None
    evidence: str | None = None        # success text / final URL proving submission
    meta: dict = field(default_factory=dict)  # e.g. resolved ats_meta from a redirect

    def __post_init__(self) -> None:
        if self.state not in APPLIER_STATES:
            raise ValueError(f"unknown applier state: {self.state}")
        if self.state == SUBMITTED and not self.evidence:
            raise ValueError("SUBMITTED requires evidence of a confirmation page")
