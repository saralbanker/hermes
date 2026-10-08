"""Tests for dashboard.app and dashboard.controls. Never calls real systemctl."""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard import app as app_module
from dashboard import controls

CSRF = {"X-Requested-With": "hermes-dashboard"}

ACTIVE_OUT = (
    "ActiveState=active\nUnitFileState=enabled\n"
    "NextElapseUSecRealtime=Wed 2026-10-08 08:00:00 IST\n"
)
PAUSED_OUT = "ActiveState=inactive\nUnitFileState=disabled\nNextElapseUSecRealtime=\n"
FRESH = {"active_state": "active", "enabled": True, "paused": False, "next_run": None}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db = tmp_path / "t.db"
    sqlite3.connect(db).close()
    monkeypatch.setenv("HERMES_DB_PATH", str(db))
    monkeypatch.setattr(app_module, "open_readonly", lambda p: sqlite3.connect(p))
    monkeypatch.setattr(app_module, "build_overview", lambda c, t, r: {"submitted_today": 3})
    monkeypatch.setattr(controls, "timer_status", lambda: dict(FRESH))
    return TestClient(app_module.create_app(), base_url="http://localhost")


def _completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_overview_ok_without_credentials(client: TestClient) -> None:
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["submitted_today"] == 3
    assert body["timer"]["active_state"] == "active"
    assert "generated_at" in body
    assert r.headers["cache-control"] == "no-store"


def test_chart_js_is_served_locally(client: TestClient) -> None:
    r = client.get("/chart.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "Chart.js v4" in r.text[:200]


def test_csp_on_all_responses(client: TestClient) -> None:
    for r in (client.get("/"), client.get("/api/overview")):
        csp = r.headers["content-security-policy"]
        assert "script-src 'self' 'unsafe-inline'" in csp
        assert "cdnjs" not in csp and "frame-ancestors 'none'" in csp


@pytest.mark.parametrize("host,status", [
    ("localhost:8787", 200), ("127.0.0.1:8787", 200), ("archlinux.tail1234.ts.net", 200),
    ("evil.example.com", 400), ("rebind.attacker.net:8787", 400),
])
def test_host_allowlist_blocks_dns_rebinding(client: TestClient, host: str, status: int) -> None:
    assert client.get("/api/overview", headers={"Host": host}).status_code == status


def test_extra_allowed_host_from_env(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("HERMES_DASH_ALLOWED_HOSTS", "dash.home.lan, other.lan")
    extra = TestClient(app_module.create_app(), base_url="http://localhost")
    assert extra.get("/api/overview", headers={"Host": "dash.home.lan"}).status_code == 200
    assert extra.get("/api/overview", headers={"Host": "nope.lan"}).status_code == 400


def test_index_serves_page_and_missing_static_is_404(client: TestClient,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    assert client.get("/").status_code == 200
    monkeypatch.setattr(app_module, "STATIC_INDEX", tmp_path / "missing.html")
    assert client.get("/").status_code == 404


def test_timer_error_does_not_500_overview(client: TestClient,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> dict:
        raise controls.TimerControlError("systemctl show failed (exit 1)")

    monkeypatch.setattr(controls, "timer_status", boom)
    r = client.get("/api/overview")
    assert r.status_code == 200
    assert r.json()["timer"] == {"error": "systemctl show failed (exit 1)"}


def test_post_requires_csrf_header(client: TestClient) -> None:
    assert client.post("/api/timer/pause").status_code == 403
    assert client.post("/api/timer/resume").status_code == 403


def test_post_calls_controls(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(controls, "pause_timer", lambda: calls.append("pause"))
    monkeypatch.setattr(controls, "resume_timer", lambda: calls.append("resume"))
    r1 = client.post("/api/timer/pause", headers=CSRF)
    r2 = client.post("/api/timer/resume", headers=CSRF)
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert r1.json() == FRESH
    assert calls == ["pause", "resume"]
    assert client.get("/api/timer").json() == FRESH


def test_nonzero_exit_gives_500(client: TestClient,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(argv: list[str], **kw: object) -> None:
        raise subprocess.CalledProcessError(1, argv, stderr="boom")

    monkeypatch.setattr(controls.subprocess, "run", fail)
    r = client.post("/api/timer/pause", headers=CSRF)
    assert r.status_code == 500
    assert "failed" in r.json()["detail"]


def test_controls_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        assert kw["check"] is True and kw["capture_output"] is True and kw["text"] is True
        return _completed(ACTIVE_OUT)

    monkeypatch.setattr(controls.subprocess, "run", fake_run)
    controls.pause_timer()
    controls.resume_timer()
    controls.timer_status()
    assert seen[0] == ["systemctl", "--user", "disable", "--now", "hermes.timer"]
    assert seen[1] == ["systemctl", "--user", "enable", "--now", "hermes.timer"]
    assert seen[2][:4] == ["systemctl", "--user", "show", "hermes.timer"]
    assert seen[2][4] == "--property=ActiveState,UnitFileState,NextElapseUSecRealtime"


@pytest.mark.parametrize(
    "out,state,enabled,next_run",
    [
        (ACTIVE_OUT, "active", True, "Wed 2026-10-08 08:00:00 IST"),
        (PAUSED_OUT, "inactive", False, None),
        ("ActiveState=active\nUnitFileState=enabled\nNextElapseUSecRealtime=0\n", "active", True, None),
        ("ActiveState=active\nUnitFileState=enabled\nNextElapseUSecRealtime=n/a\n", "active", True, None),
    ],
)
def test_timer_status_parsing(monkeypatch: pytest.MonkeyPatch, out: str, state: str,
                              enabled: bool, next_run: str | None) -> None:
    monkeypatch.setattr(controls.subprocess, "run", lambda *a, **k: _completed(out))
    status = controls.timer_status()
    assert status == {"active_state": state, "enabled": enabled,
                      "paused": not enabled, "next_run": next_run}
