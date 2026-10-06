"""Message processing pipeline — correlate -> classify -> notification_level
-> persist (responses_v2) -> Telegram delivery, with message_id idempotency.

DATA_MODEL.md §11.6: `Ignore`-tier events produce no durable record by
definition — an uncorrelated message, or a correlated `acknowledgement`,
is never written to `responses_v2` at all; only Log/Telegram Notification/
High Priority Telegram Notification rows are persisted.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import classify as classify_mod
from . import correlate as correlate_mod
from . import notification
from . import telegram as telegram_mod
from .. import db as enginedb


@dataclass(frozen=True)
class ProcessResult:
    duplicate: bool
    persisted: bool
    category: str | None
    notification_level: str
    opportunity_id: int | None
    notified: bool


def _already_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM responses_v2 WHERE message_id = ?", (message_id,)
    ).fetchone() is not None


def _build_telegram_text(category: str, company: str, subject: str) -> str:
    label = category.replace("_", " ").title()
    return f"Hermes: {label}\nCompany: {company}\nSubject: {subject}"


def _persist(conn: sqlite3.Connection, message_id: str, from_addr: str, subject: str,
             received_at: str, category: str, level: str,
             correlation: correlate_mod.CorrelationResult, now: str) -> None:
    conn.execute(
        """
        INSERT INTO responses_v2 (
            message_id, from_addr, subject, received_at, classification,
            opportunity_id, attempt_id, notification_level, correlation_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (message_id, from_addr, subject, received_at, category,
         correlation.opportunity_id, correlation.attempt_id, level, correlation.reason, now),
    )


def process_message(
    conn: sqlite3.Connection, message_id: str, from_addr: str, subject: str, body: str,
    received_at: str, *, send_fn=telegram_mod.send_message, now: str | None = None,
) -> ProcessResult:
    now = now or enginedb.now_iso()
    if _already_processed(conn, message_id):
        return ProcessResult(True, False, None, notification.IGNORE, None, False)

    correlation = correlate_mod.correlate(conn, from_addr, subject, body)
    if correlation is None:
        return ProcessResult(False, False, None, notification.IGNORE, None, False)

    category = classify_mod.classify(subject, body)
    level = notification.level_for(category)
    if level not in notification.PERSISTED_TIERS:
        return ProcessResult(False, False, category, level, correlation.opportunity_id, False)

    _persist(conn, message_id, from_addr, subject, received_at, category, level, correlation, now)

    notified = False
    if level in notification.TELEGRAM_TIERS:
        notified = _try_notify(send_fn, category, correlation.company, subject)
        if notified:
            conn.execute(
                "UPDATE responses_v2 SET notified_at = ? WHERE message_id = ?", (now, message_id)
            )
    conn.commit()
    return ProcessResult(False, True, category, level, correlation.opportunity_id, notified)


def _try_notify(send_fn, category: str, company: str, subject: str) -> bool:
    try:
        return bool(send_fn(_build_telegram_text(category, company, subject)))
    except telegram_mod.TelegramUnavailable:
        return False  # logged by the caller's watcher loop, never crashes processing
