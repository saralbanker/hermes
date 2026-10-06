"""Phase 5: scripts/hermes_engine_worker.py's lock mechanism — same flock(2)
primitive scripts/run_hermes.sh uses for the legacy path, applied to a
separate lock file. A second instance must refuse to start, not block."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location(
    "hermes_engine_worker", ROOT / "scripts" / "hermes_engine_worker.py"
)
hermes_engine_worker = importlib.util.module_from_spec(spec)
sys.modules["hermes_engine_worker"] = hermes_engine_worker
spec.loader.exec_module(hermes_engine_worker)


def test_second_lock_attempt_is_refused_while_first_holds_it(tmp_path, monkeypatch):
    lock_path = tmp_path / "hermes-engine.lock"
    monkeypatch.setattr(hermes_engine_worker, "LOCK_PATH", lock_path)

    fh1 = hermes_engine_worker.acquire_lock()
    assert fh1 is not None

    fh2 = hermes_engine_worker.acquire_lock()
    assert fh2 is None  # refused — no overlap, matches flock -n semantics

    fh1.close()
    fh3 = hermes_engine_worker.acquire_lock()
    assert fh3 is not None  # released after close(), lock available again
    fh3.close()


def test_lock_file_contains_pid(tmp_path, monkeypatch):
    lock_path = tmp_path / "hermes-engine.lock"
    monkeypatch.setattr(hermes_engine_worker, "LOCK_PATH", lock_path)
    fh = hermes_engine_worker.acquire_lock()
    assert fh is not None
    fh.close()
    assert lock_path.read_text().strip().isdigit()
