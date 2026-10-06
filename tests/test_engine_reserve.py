"""Phase 2 engine: READY_RESERVE predicate correctness (DATA_MODEL.md §26,
post Patch 1) and work_queue rebuild (§9.4/§17, §152 Queue Rebuild Test)."""

import datetime as dt

from engine import db as enginedb, reserve


def test_ready_reserve_counts_only_ready_eligible_open(make_opportunity, engine_conn):
    make_opportunity("canon::r1", application_state="READY")
    make_opportunity("canon::r2", application_state="READY")
    # Not counted: still EVALUATING (this is the exact bug Patch 1 fixes —
    # pre-patch predicate, using `application_state NOT IN (...)`, would
    # have wrongly counted this).
    make_opportunity("canon::r3", application_state="EVALUATING")
    # Not counted: OBSERVED.
    make_opportunity("canon::r4", application_state="OBSERVED")
    # Not counted: APPLYING (live attempt).
    make_opportunity("canon::r5", application_state="APPLYING")
    # Not counted: COMPLETED.
    make_opportunity("canon::r6", application_state="COMPLETED")
    # Not counted: ineligible.
    make_opportunity("canon::r7", application_state="READY", hard_eligibility_state="INELIGIBLE")
    # Not counted: permanently blocked (no supported route).
    make_opportunity(
        "canon::r8", application_state="READY", hard_eligibility_reason="NO_SUPPORTED_ROUTE"
    )

    assert reserve.compute_ready_reserve(engine_conn) == 2


def test_ready_reserve_excludes_pending_backoff(make_opportunity, engine_conn):
    opp_id = make_opportunity("canon::backoff")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    engine_conn.execute(
        "UPDATE work_queue SET next_attempt_at = ? WHERE opportunity_id = ?", (future, opp_id)
    )
    assert reserve.compute_ready_reserve(engine_conn) == 0


def test_ready_reserve_excludes_expired_age_band(make_opportunity, engine_conn):
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    make_opportunity("canon::old", age_reference_at=old_ts)
    assert reserve.compute_ready_reserve(engine_conn) == 0


def test_queue_rebuild_restores_actionable_work_and_excludes_others(make_opportunity, engine_conn):
    """§152 Queue Rebuild Test: clear queue projection -> rebuild ->
    actionable work restored -> submitted/expired/ineligible work excluded."""
    ready_id = make_opportunity("canon::ready")
    make_opportunity("canon::completed", application_state="COMPLETED")
    old_ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    make_opportunity("canon::expired", age_reference_at=old_ts)
    make_opportunity("canon::ineligible", hard_eligibility_state="INELIGIBLE")

    engine_conn.execute("DELETE FROM work_queue")
    inserted = reserve.rebuild_work_queue(engine_conn)

    assert inserted == 1
    rows = engine_conn.execute("SELECT opportunity_id FROM work_queue").fetchall()
    assert [r["opportunity_id"] for r in rows] == [ready_id]


def test_queue_rebuild_preserves_backoff_timer(make_opportunity, engine_conn):
    opp_id = make_opportunity("canon::preserve")
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    engine_conn.execute(
        "UPDATE work_queue SET next_attempt_at = ? WHERE opportunity_id = ?", (future, opp_id)
    )

    reserve.rebuild_work_queue(engine_conn)

    row = engine_conn.execute(
        "SELECT next_attempt_at FROM work_queue WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert row["next_attempt_at"] == future
