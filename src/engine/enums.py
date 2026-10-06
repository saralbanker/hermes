"""Canonical enums for the Phase 2 execution engine.

Single source of truth for the four state dimensions WORKFLOW_ENGINE.md §4
defines and DATA_MODEL.md §5.9/§7.4/§7.5/§8.3 schema-constrains (the exact
same value sets as the CHECK constraints baked into
db/migrations/0001_opportunity_model.sql). This module is net-new and does
not replace or import from src/states.py, which keeps its own (currently
drifted) enum set for the legacy, still-running pipeline — reconciling that
drift is explicitly out of scope until the legacy path is retired.
"""

from __future__ import annotations

from enum import Enum


class ApplicationState(str, Enum):
    """opportunities.application_state — DATA_MODEL.md §5.9."""

    OBSERVED = "OBSERVED"
    EVALUATING = "EVALUATING"
    READY = "READY"
    APPLYING = "APPLYING"
    AWAITING_RECONCILIATION = "AWAITING_RECONCILIATION"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ExecutionPhase(str, Enum):
    """application_attempts.execution_phase — DATA_MODEL.md §7.5.

    Monotonic forward-only progression; answers "did external, possibly
    irreversible work begin before the process died."
    """

    NOT_STARTED = "NOT_STARTED"
    EXTERNAL_WORK_STARTED = "EXTERNAL_WORK_STARTED"
    SUBMIT_INTENT = "SUBMIT_INTENT"
    OBSERVED = "OBSERVED"


class Outcome(str, Enum):
    """application_attempts.outcome — DATA_MODEL.md §7.4 / WORKFLOW_ENGINE.md §67."""

    SUBMITTED = "SUBMITTED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    SUBMISSION_UNCONFIRMED = "SUBMISSION_UNCONFIRMED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    CHANNEL_BLOCKED = "CHANNEL_BLOCKED"
    UNSUPPORTED_CHANNEL = "UNSUPPORTED_CHANNEL"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


# Outcomes that represent a confirmed, duplicate-protected disposition
# (DATA_MODEL.md §12.3 / WORKFLOW_ENGINE.md §64 "Duplicate Prevention").
CONFIRMED_OUTCOMES = frozenset({Outcome.SUBMITTED, Outcome.ALREADY_APPLIED})


class ChannelStatus(str, Enum):
    """channel_health.status — DATA_MODEL.md §8.3 (10-value set)."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    FORM_SCHEMA_CHANGED = "FORM_SCHEMA_CHANGED"
    ACCOUNT_WALL = "ACCOUNT_WALL"
    ANTIBOT_BLOCKED = "ANTIBOT_BLOCKED"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    PAUSED = "PAUSED"


# Channel statuses that block new submission attempts on that route
# (WORKFLOW_ENGINE.md §51 cooldown triggers / BROWSER_SYSTEM.md §103.1).
BLOCKING_CHANNEL_STATUSES = frozenset(
    {
        ChannelStatus.AUTH_EXPIRED,
        ChannelStatus.RATE_LIMITED,
        ChannelStatus.FORM_SCHEMA_CHANGED,
        ChannelStatus.ACCOUNT_WALL,
        ChannelStatus.ANTIBOT_BLOCKED,
        ChannelStatus.NETWORK_UNAVAILABLE,
        ChannelStatus.UNSUPPORTED,
        ChannelStatus.PAUSED,
    }
)

AGE_BANDS_IN_ORDER = ("0_3D", "4_7D", "8_14D", "15_21D")
AGE_BAND_EXPIRED = "EXPIRED"
ALL_AGE_BANDS = AGE_BANDS_IN_ORDER + (AGE_BAND_EXPIRED,)
