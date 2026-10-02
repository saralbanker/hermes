"""Phase 6: src/engine/gmail/pipeline.py — correlate -> classify -> persist
-> notify, with message_id idempotency (DATA_MODEL.md §11.6/§18)."""
from __future__ import annotations

from engine import claim, db as enginedb
from engine.gmail import notification, pipeline


def _claimed(make_opportunity, seed_channel, engine_conn, key, company):
    seed_channel("indeed")
    make_opportunity(key, company_display=company)
    return claim.claim_next(engine_conn, worker_id="w1", lease_seconds=900)


def test_human_required_message_persists_and_notifies(make_opportunity, seed_channel, engine_conn):
    claimed = _claimed(make_opportunity, seed_channel, engine_conn, "canon::p1", "Acme Robotics")
    sent = {"calls": []}

    result = pipeline.process_message(
        engine_conn, "<msg1@test>", "careers@acmerobotics.com", "Interview invitation",
        "We'd like to schedule a call — please select a time via Calendly.", enginedb.now_iso(),
        send_fn=lambda text: sent["calls"].append(text) or True,
    )
    assert result.persisted is True
    assert result.notification_level == notification.HIGH_PRIORITY
    assert result.notified is True
    assert len(sent["calls"]) == 1

    row = engine_conn.execute(
        "SELECT * FROM responses_v2 WHERE message_id = '<msg1@test>'"
    ).fetchone()
    assert row["opportunity_id"] == claimed.opportunity_id
    assert row["classification"] == "human_required_signal"
    assert row["notified_at"] is not None


def test_reprocessing_same_message_id_does_not_renotify(make_opportunity, seed_channel, engine_conn):
    _claimed(make_opportunity, seed_channel, engine_conn, "canon::p2", "Globex Corp")
    sent = {"n": 0}

    def send_fn(text):
        sent["n"] += 1
        return True

    args = (engine_conn, "<msg2@test>", "careers@globexcorp.com", "Interview invitation",
            "schedule a call via calendly", enginedb.now_iso())
    r1 = pipeline.process_message(*args, send_fn=send_fn)
    r2 = pipeline.process_message(*args, send_fn=send_fn)

    assert r1.duplicate is False
    assert r2.duplicate is True
    assert sent["n"] == 1  # never re-notified on reprocess

    count = engine_conn.execute(
        "SELECT COUNT(*) AS n FROM responses_v2 WHERE message_id = '<msg2@test>'"
    ).fetchone()["n"]
    assert count == 1


def test_acknowledgement_is_never_persisted(make_opportunity, seed_channel, engine_conn):
    _claimed(make_opportunity, seed_channel, engine_conn, "canon::p3", "Initech")
    result = pipeline.process_message(
        engine_conn, "<msg3@test>", "careers@initech.com", "Application received",
        "Thank you for applying. We have received your application.", enginedb.now_iso(),
    )
    assert result.persisted is False
    assert result.notification_level == notification.IGNORE
    row = engine_conn.execute(
        "SELECT * FROM responses_v2 WHERE message_id = '<msg3@test>'"
    ).fetchone()
    assert row is None


def test_uncorrelated_message_is_never_persisted(engine_conn):
    result = pipeline.process_message(
        engine_conn, "<msg4@test>", "jobalerts-noreply@indeed.com", "Recommended jobs",
        "Check out these jobs.", enginedb.now_iso(),
    )
    assert result.persisted is False
    assert result.category is None


def test_telegram_failure_does_not_crash_processing(make_opportunity, seed_channel, engine_conn):
    from engine.gmail import telegram
    _claimed(make_opportunity, seed_channel, engine_conn, "canon::p5", "Hooli")

    def boom(text):
        raise telegram.TelegramUnavailable("no credentials")

    result = pipeline.process_message(
        engine_conn, "<msg5@test>", "careers@hooli.com", "Interview invitation",
        "schedule a call via calendly", enginedb.now_iso(), send_fn=boom,
    )
    assert result.persisted is True
    assert result.notified is False
    row = engine_conn.execute(
        "SELECT notified_at FROM responses_v2 WHERE message_id = '<msg5@test>'"
    ).fetchone()
    assert row["notified_at"] is None


def test_rejection_persists_but_no_telegram_call(make_opportunity, seed_channel, engine_conn):
    _claimed(make_opportunity, seed_channel, engine_conn, "canon::p6", "Soylent Corp")
    called = {"n": 0}
    result = pipeline.process_message(
        engine_conn, "<msg6@test>", "careers@soylentcorp.com", "Application update",
        "Unfortunately we have decided to move forward with other candidates.", enginedb.now_iso(),
        send_fn=lambda text: called.__setitem__("n", called["n"] + 1) or True,
    )
    assert result.persisted is True
    assert result.notification_level == notification.LOG
    assert called["n"] == 0  # Log tier never calls Telegram
