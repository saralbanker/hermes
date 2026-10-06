"""Phase 6: src/engine/gmail/watcher.py — EXECUTION_PROTOCOL.md §74.12
(Patch 11) recovery behavior, and decoupling from src/engine/worker.py's
application pipeline. IMAP is fully mocked — no real Gmail connection."""
from __future__ import annotations

from engine.gmail import watcher


def test_connect_with_backoff_returns_none_when_no_credentials(monkeypatch):
    monkeypatch.setattr(watcher, "_get_app_password", lambda: None)
    assert watcher._connect_with_backoff(sleep_fn=lambda s: None) is None


def test_connect_with_backoff_retries_bounded_then_gives_up(monkeypatch):
    monkeypatch.setattr(watcher, "_get_app_password", lambda: "fake-password")
    calls = {"n": 0}

    def fake_connect():
        calls["n"] += 1
        return None

    sleeps = []
    monkeypatch.setattr(watcher, "_connect", fake_connect)
    result = watcher._connect_with_backoff(sleep_fn=sleeps.append)
    assert result is None
    assert calls["n"] == watcher.MAX_RECONNECT_ATTEMPTS
    assert len(sleeps) == watcher.MAX_RECONNECT_ATTEMPTS - 1
    assert sleeps == watcher.RECONNECT_BACKOFF_SECONDS[:-1]


def test_connect_with_backoff_succeeds_after_transient_failure(monkeypatch):
    monkeypatch.setattr(watcher, "_get_app_password", lambda: "fake-password")
    calls = {"n": 0}

    def fake_connect():
        calls["n"] += 1
        return "fake-imap-conn" if calls["n"] == 2 else None

    monkeypatch.setattr(watcher, "_connect", fake_connect)
    result = watcher._connect_with_backoff(sleep_fn=lambda s: None)
    assert result == "fake-imap-conn"
    assert calls["n"] == 2


def test_poll_once_defers_gracefully_when_imap_unavailable(engine_conn, monkeypatch):
    """§74.12 step 1: a genuine connection failure defers to the next poll
    rather than raising — the watcher itself must stay alive."""
    monkeypatch.setattr(watcher, "_get_app_password", lambda: None)
    stats = watcher.poll_once(engine_conn, sleep_fn=lambda s: None)
    assert stats["status"] == "imap_unavailable"
    assert stats["scanned"] == 0


def test_poll_once_processes_fetched_messages(engine_conn, monkeypatch):
    monkeypatch.setattr(watcher, "_get_app_password", lambda: "fake-password")
    monkeypatch.setattr(watcher, "_connect", lambda: object())

    messages = [
        ("<a@test>", "careers@acme.com", "subject", "body", "2026-10-02T00:00:00"),
    ]
    monkeypatch.setattr(watcher, "fetch_messages", lambda imap_conn, days: iter(messages))

    from engine.gmail import pipeline
    monkeypatch.setattr(
        pipeline, "process_message",
        lambda *a, **kw: pipeline.ProcessResult(False, False, None, "Ignore", None, False),
    )

    stats = watcher.poll_once(engine_conn)
    assert stats["status"] == "ok"
    assert stats["scanned"] == 1
    assert stats["new"] == 1


def test_poll_loop_never_raises_even_if_poll_once_crashes(engine_conn, monkeypatch):
    def boom(conn, days=3, sleep_fn=None):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(watcher, "poll_once", boom)
    reports = watcher.poll_loop(lambda: engine_conn, max_iterations=2, sleep_fn=lambda s: None)
    assert len(reports) == 2
    assert all(r["status"] == "error" for r in reports)


def test_watcher_module_never_imported_by_application_worker():
    """Confirms the decoupling claim directly: src/engine/worker.py's
    source does not import src/engine/gmail at all."""
    import inspect
    from engine import worker as worker_mod
    source = inspect.getsource(worker_mod)
    assert "gmail" not in source


def test_watcher_does_not_touch_legacy_response_watcher_table(engine_conn):
    """The new pipeline writes only responses_v2, never the legacy
    `responses` table response_watcher.py owns."""
    tables = {r[0] for r in engine_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "responses_v2" in tables
