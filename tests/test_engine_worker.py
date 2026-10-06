"""Phase 5: src/engine/worker.py — the continuous worker loop. No network,
no real browser/Ollama: every stage (discovery, evaluation, claim/apply,
maintenance) is mocked at its own module boundary, same pattern as every
other phase's tests."""
from __future__ import annotations

import pytest

import engine_apply
from engine import discovery, evaluation, worker as worker_mod
from engine.ai import resource_arbiter as ra
from engine.worker import CycleReport, Worker, WorkerPolicy

ENABLED_CFG = {"engine": {"enabled": True}}
DISABLED_CFG = {"engine": {"enabled": False}}


def _worker(engine_conn, cfg=ENABLED_CFG, policy=None):
    return Worker(engine_conn, cfg, policy or WorkerPolicy())


def test_worker_fails_closed_when_engine_disabled(engine_conn):
    w = _worker(engine_conn, cfg=DISABLED_CFG)
    with pytest.raises(engine_apply.EngineDisabledError):
        w.startup()


def test_worker_startup_runs_recovery_and_expiration(engine_conn, monkeypatch):
    calls = {"recovery": 0, "expire": 0}
    monkeypatch.setattr(worker_mod, "run_startup_recovery",
                         lambda conn: calls.__setitem__("recovery", calls["recovery"] + 1) or
                         {"recovered_leases": 0, "work_queue_rows": 0})
    monkeypatch.setattr(worker_mod, "expire_stale_opportunities",
                         lambda conn: calls.__setitem__("expire", calls["expire"] + 1) or 0)
    _worker(engine_conn).startup()
    assert calls == {"recovery": 1, "expire": 1}


def test_run_cycle_skips_discovery_when_not_due(engine_conn, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: None)

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=9999))
    w._last_discovery = __import__("time").monotonic()  # just ran
    report = w.run_cycle()
    assert called["n"] == 0
    assert report.discovered is None


def test_run_cycle_runs_discovery_when_due(engine_conn, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(discovery, "run_discovery_cycle",
                         lambda *a, **kw: called.__setitem__("n", called["n"] + 1) or {"raw": 0})
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: None)

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=0))
    report = w.run_cycle()
    assert called["n"] == 1
    assert report.discovered == {"raw": 0}


def test_run_cycle_defers_evaluation_over_rss_ceiling(engine_conn, monkeypatch):
    monkeypatch.setattr(ra, "arbitrate_model_load", lambda **kw: ra.ArbitrationDecision(
        False, "over ceiling", 0, 0, 0, 0))
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: {"raw": 0})
    eval_called = {"n": 0}
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: eval_called.__setitem__("n", 1))
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: None)

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=9999))
    report = w.run_cycle()
    assert eval_called["n"] == 0
    assert report.deferred_ai is True


def test_run_cycle_defers_claim_over_rss_ceiling(engine_conn, monkeypatch):
    monkeypatch.setattr(ra, "arbitrate_browser_open", lambda **kw: ra.ArbitrationDecision(
        False, "over ceiling", 0, 0, 0, 0))
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: {"raw": 0})
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    claim_called = {"n": 0}
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine",
                         lambda *a, **kw: claim_called.__setitem__("n", 1))

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=9999))
    report = w.run_cycle()
    assert claim_called["n"] == 0
    assert report.deferred_claim is True


def test_run_cycle_claims_and_applies_when_resources_available(engine_conn, monkeypatch):
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: {"raw": 0})
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    sentinel = object()
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: sentinel)

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=9999))
    report = w.run_cycle()
    assert report.claimed_outcome is sentinel
    assert report.idle is False


def test_run_cycle_marks_idle_when_nothing_claimed(engine_conn, monkeypatch):
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: {"raw": 0})
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: None)

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=9999))
    report = w.run_cycle()
    assert report.idle is True


def test_maintenance_runs_only_when_due(engine_conn, monkeypatch):
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: {"raw": 0})
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: None)
    calls = {"n": 0}
    monkeypatch.setattr(worker_mod, "run_startup_recovery",
                         lambda conn: calls.__setitem__("n", calls["n"] + 1) or {})
    monkeypatch.setattr(worker_mod, "expire_stale_opportunities", lambda conn: 0)

    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=9999,
                                                  maintenance_interval_seconds=0))
    report = w.run_cycle()
    assert report.maintenance_ran is True
    assert calls["n"] == 1


def test_backoff_increases_with_idle_streak_and_is_capped(engine_conn):
    w = _worker(engine_conn, policy=WorkerPolicy(idle_sleep_seconds=10, idle_backoff_max_seconds=35))
    w._idle_streak = 0
    first = w._backoff_seconds()
    w._idle_streak = 1
    second = w._backoff_seconds()
    w._idle_streak = 100
    capped = w._backoff_seconds()
    assert first < second
    assert capped == 35


def test_run_stops_at_max_iterations_and_sleeps_on_idle(engine_conn, monkeypatch):
    monkeypatch.setattr(worker_mod, "run_startup_recovery", lambda conn: {"recovered_leases": 0, "work_queue_rows": 0})
    monkeypatch.setattr(worker_mod, "expire_stale_opportunities", lambda conn: 0)
    monkeypatch.setattr(discovery, "run_discovery_cycle", lambda *a, **kw: {"raw": 0})
    monkeypatch.setattr(evaluation, "evaluate_batch", lambda *a, **kw: {})
    monkeypatch.setattr(engine_apply, "apply_indeed_via_engine", lambda *a, **kw: None)

    sleeps = []
    w = _worker(engine_conn, policy=WorkerPolicy(discovery_interval_seconds=0, maintenance_interval_seconds=0))
    summary = w.run(max_iterations=3, sleep_fn=sleeps.append)

    assert summary["iterations"] == 3
    assert len(sleeps) == 3
    assert sleeps[0] < sleeps[1] < sleeps[2]  # idle backoff growing
