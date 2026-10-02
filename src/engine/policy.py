"""Frozen policy constants and the Retry Matrix.

Sources:
    WORKFLOW_ENGINE.md §9  (READY_RESERVE_TARGET)
    WORKFLOW_ENGINE.md §22/§23 (MAX_ATTEMPTS, backoff)
    WORKFLOW_ENGINE.md §27/§83 (daily confirmed target)
    WORKFLOW_ENGINE.md §114 (Retry Matrix)
    ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §3.2 (age-band hour boundaries)
"""

from __future__ import annotations

from .enums import Outcome

MAX_ATTEMPTS = 3
READY_RESERVE_TARGET = 300
DAILY_CONFIRMED_TARGET = 100

# ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §3.2 / DATA_MODEL.md §27.1:
# 0-72h / >72-168h / >168-336h / >336-504h / >504h = EXPIRED
AGE_BAND_HOUR_BOUNDARIES = (
    ("0_3D", 72),
    ("4_7D", 168),
    ("8_14D", 336),
    ("15_21D", 504),
)

# WORKFLOW_ENGINE.md §23: "attempt 1 -> short delay, attempt 2 -> longer
# delay, attempt 3 -> no further automatic retry". "Exact timing is
# configurable" — these defaults are this implementation's chosen values,
# not specified numerically by any doc.
RETRY_BACKOFF_SECONDS = {
    1: 15 * 60,       # short delay after attempt 1
    2: 2 * 60 * 60,   # longer delay after attempt 2
    # no entry for 3: MAX_ATTEMPTS reached, no further automatic retry
}

DEFAULT_LEASE_SECONDS = 15 * 60


# --- Retry Matrix (WORKFLOW_ENGINE.md §114) -------------------------------
# Maps a failure condition to whether it is eligible for bounded automatic
# retry. This is the input DATA_MODEL.md §7.4 says is consumed to compute
# application_attempts.retry_eligible: "1 if and only if outcome/error_class
# falls in the bounded-retry / bounded-reinspection / channel-cooldown rows
# of Section 114's Retry Matrix; 0 for SUBMITTED, ALREADY_APPLIED,
# SUBMISSION_UNCONFIRMED (reconciliation-gated), UNSUPPORTED_CHANNEL, and
# TERMINAL_FAILURE."
RETRYABLE_CONDITIONS = frozenset(
    {
        "network_timeout_before_external_action",  # bounded retry
        "model_unavailable_before_external_action",  # defer/retry
        "form_changed",  # bounded reinspection
        "rate_limit",  # channel cooldown
    }
)

NON_RETRYABLE_CONDITIONS = frozenset(
    {
        "authentication_expired",  # wait for channel recovery (not automatic retry)
        "captcha",  # stop route; no bypass
        "anti_bot_block",  # stop same-route retry
        "ambiguous_submit",  # reconcile first
        "confirmed_submit",  # no retry
        "already_applied",  # no retry
        "expired_horizon",  # no claim
    }
)


def retry_eligible_bit(outcome: Outcome, error_class: str | None) -> int:
    """DATA_MODEL.md §7.4: the attempt-level retry_eligible bit.

    Set once, when the attempt finishes, from this attempt's own outcome and
    error_class only — never recomputed later.
    """
    if outcome in (
        Outcome.SUBMITTED,
        Outcome.ALREADY_APPLIED,
        Outcome.SUBMISSION_UNCONFIRMED,
        Outcome.UNSUPPORTED_CHANNEL,
        Outcome.TERMINAL_FAILURE,
    ):
        return 0
    if outcome in (Outcome.RETRYABLE_FAILURE, Outcome.CHANNEL_BLOCKED):
        if error_class and error_class in RETRYABLE_CONDITIONS:
            return 1
        if outcome is Outcome.RETRYABLE_FAILURE and error_class is None:
            # RETRYABLE_FAILURE with no further classification is, by
            # definition of the outcome name, a bounded-retry row.
            return 1
        return 0
    return 0
