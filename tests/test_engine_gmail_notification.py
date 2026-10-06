"""Phase 6: src/engine/gmail/notification.py — category -> notification_level
mapping (WORKFLOW_ENGINE.md §62, Patch 10), with the automation-boundary
categories always landing on High Priority."""
from __future__ import annotations

from engine.gmail import classify, notification


def test_human_required_signal_always_high_priority():
    assert notification.level_for(classify.HUMAN_REQUIRED_SIGNAL) == notification.HIGH_PRIORITY


def test_rejection_is_log():
    assert notification.level_for(classify.REJECTION) == notification.LOG


def test_screening_follow_up_is_log():
    assert notification.level_for(classify.SCREENING_FOLLOW_UP) == notification.LOG


def test_ambiguous_is_telegram_notification():
    assert notification.level_for(classify.AMBIGUOUS) == notification.TELEGRAM_NOTIFICATION


def test_acknowledgement_is_ignore():
    assert notification.level_for(classify.ACKNOWLEDGEMENT) == notification.IGNORE


def test_exact_wording_matches_data_model_11_6():
    assert notification.IGNORE == "Ignore"
    assert notification.LOG == "Log"
    assert notification.TELEGRAM_NOTIFICATION == "Telegram Notification"
    assert notification.HIGH_PRIORITY == "High Priority Telegram Notification"


def test_telegram_tiers_exclude_log_and_ignore():
    assert notification.LOG not in notification.TELEGRAM_TIERS
    assert notification.IGNORE not in notification.TELEGRAM_TIERS
    assert notification.TELEGRAM_NOTIFICATION in notification.TELEGRAM_TIERS
    assert notification.HIGH_PRIORITY in notification.TELEGRAM_TIERS


def test_ignore_tier_excluded_from_persisted_tiers():
    """DATA_MODEL.md §11.6: 'Ignore-tier events produce no durable record
    by definition.'"""
    assert notification.IGNORE not in notification.PERSISTED_TIERS
    assert notification.LOG in notification.PERSISTED_TIERS
