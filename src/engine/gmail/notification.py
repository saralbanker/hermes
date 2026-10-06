"""Classification -> notification_level — WORKFLOW_ENGINE.md §62 (Patch 10),
DATA_MODEL.md §11.6. Exact wording required by §11.6: `Ignore`, `Log`,
`Telegram Notification`, `High Priority Telegram Notification`.
"""

from __future__ import annotations

from .classify import (
    ACKNOWLEDGEMENT,
    AMBIGUOUS,
    HUMAN_REQUIRED_SIGNAL,
    REJECTION,
    SCREENING_FOLLOW_UP,
)

IGNORE = "Ignore"
LOG = "Log"
TELEGRAM_NOTIFICATION = "Telegram Notification"
HIGH_PRIORITY = "High Priority Telegram Notification"

# WORKFLOW_ENGINE.md §62's five routing rows, verbatim.
LEVEL_BY_CATEGORY = {
    SCREENING_FOLLOW_UP: LOG,
    HUMAN_REQUIRED_SIGNAL: HIGH_PRIORITY,
    REJECTION: LOG,
    AMBIGUOUS: TELEGRAM_NOTIFICATION,
    ACKNOWLEDGEMENT: IGNORE,
}

# Tiers that actually deliver a Telegram message (src/engine/gmail/telegram.py).
TELEGRAM_TIERS = frozenset({TELEGRAM_NOTIFICATION, HIGH_PRIORITY})

# DATA_MODEL.md §11.6: "Ignore-tier events produce no durable record by
# definition... a `responses` row that exists at all is expected to carry
# Log, Telegram Notification, or High Priority Telegram Notification."
PERSISTED_TIERS = frozenset({LOG, TELEGRAM_NOTIFICATION, HIGH_PRIORITY})


def level_for(category: str) -> str:
    return LEVEL_BY_CATEGORY.get(category, IGNORE)
