"""Ollama down / timing out must degrade to deterministic paths, never crash a run."""
import requests

import llm
from llm import LLMUnavailable


def _down(*a, **k):
    raise requests.ConnectionError("connection refused")


def test_chat_and_embed_wrap_transport_errors(monkeypatch):
    monkeypatch.setattr(requests, "post", _down)
    for call in (lambda: llm.chat("hi"), lambda: llm.embed(["x"])):
        try:
            call()
            raise AssertionError("expected LLMUnavailable")
        except LLMUnavailable:
            pass


def test_timeout_is_unavailable_not_crash(monkeypatch):
    def slow(*a, **k):
        raise requests.Timeout("read timed out")
    monkeypatch.setattr(requests, "post", slow)
    try:
        llm.chat("hi")
        raise AssertionError("expected LLMUnavailable")
    except LLMUnavailable:
        pass


def test_missing_model_404_is_unavailable(monkeypatch):
    class Resp:
        status_code = 404
        def raise_for_status(self):
            raise requests.HTTPError("404 model not found")
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp())
    try:
        llm.chat("hi")
        raise AssertionError("expected LLMUnavailable")
    except LLMUnavailable:
        pass


def test_tailor_falls_back_to_fact_template(monkeypatch):
    import tailor
    monkeypatch.setattr(requests, "post", _down)
    letter, source = tailor.generate_cover_letter(
        {"company": "Acme", "title": "Backend Engineer", "description": "Python APIs"}, [], "backend")
    assert source == "template" and not tailor.validate_letter(letter)


def test_score_falls_back_to_keywords(monkeypatch):
    import score
    monkeypatch.setattr(requests, "post", _down)
    s, reason, still_llm = score._score_one(
        {"company": "A", "title": "Python Backend Engineer", "location": "Remote",
         "description": "python fastapi postgresql redis docker react typescript node"}, True)
    assert 1 <= s <= 10 and "keyword" in reason and still_llm is False


def test_answers_return_none_instead_of_guessing(monkeypatch):
    from answers import answer_question
    monkeypatch.setattr(requests, "post", _down)
    assert answer_question("Describe a time you scaled a Kafka cluster", kind="textarea") is None


def test_cleanup_orphan_browsers_removes_stale_locks(tmp_path):
    import display
    prof = tmp_path / "output" / "chrome-indeed-profile"
    prof.mkdir(parents=True)
    lock = prof / "SingletonLock"
    lock.symlink_to("nonexistent-host-999999")
    assert lock.is_symlink()

    cleaned = display.cleanup_orphan_browsers(root_dir=tmp_path)
    assert cleaned["locks_removed"] == 1
    assert not lock.exists()


def test_ensure_virtual_display_idempotent(monkeypatch):
    import display
    import psutil
    # Verify that ensure_virtual_display is idempotent and does not kill active display
    d1 = display.ensure_virtual_display()
    try:
        proc1 = display._proc
        assert proc1 is not None and proc1.poll() is None
        pid1 = proc1.pid
        d2 = display.ensure_virtual_display()
        assert d1 == d2
        assert display._proc.pid == pid1
        assert psutil.pid_exists(pid1)
    finally:
        display._stop()


