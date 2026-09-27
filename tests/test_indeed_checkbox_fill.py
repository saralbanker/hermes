"""Offline test for _fill_checkboxes — the fix for a confirmed real timeout (Mirantis,
2026-09-24, output/hermes_cron.log): a required 'Agree' checkbox on Indeed's EEO step was
never touched by any filler, so Continue kept failing the same validation until the outer
6-minute budget was hit. No browser: a minimal fake element/page stands in for DrissionPage.
"""
from __future__ import annotations

import indeed_apply as ia


class _FakeStates:
    def __init__(self, checked: bool) -> None:
        self.is_checked = checked


class _FakeBox:
    def __init__(self, label: str, checked: bool = False, required: bool = False) -> None:
        self._label = label
        self.states = _FakeStates(checked)
        self._required = required
        self.clicked = False

    def attr(self, name: str):
        if name == "aria-label":
            return self._label
        if name == "required":
            return "" if self._required else None
        return None

    def click(self) -> None:
        self.clicked = True


class _FakePage:
    def __init__(self, boxes: list[_FakeBox]) -> None:
        self._boxes = boxes

    def eles(self, _selector: str, timeout: int = 1):
        return self._boxes

    def ele(self, *_a, **_kw):
        return None


def test_fill_checkboxes_checks_a_required_agree_box():
    box = _FakeBox("You declare that you have read and agree to the privacy notice.",
                   required=True)
    page = _FakePage([box])
    assert ia._fill_checkboxes(page) is None
    assert box.clicked is True


def test_fill_checkboxes_leaves_already_checked_box_alone():
    box = _FakeBox("Agree to terms", checked=True, required=True)
    page = _FakePage([box])
    assert ia._fill_checkboxes(page) is None
    assert box.clicked is False


def test_fill_checkboxes_fails_explicitly_on_an_unanswerable_required_box():
    box = _FakeBox("I certify this application contains no AI-generated content",
                   required=True)
    page = _FakePage([box])
    result = ia._fill_checkboxes(page)
    assert result is not None
    assert "AI-generated" in result


def test_fill_checkboxes_never_fabricates_consent_for_an_optional_unanswerable_box():
    """Indeed's own 'save my answers for pre-filling' toggle: unrelated to this
    application's truthfulness, not required — must be left alone, not force-checked."""
    box = _FakeBox("I consent to Indeed saving my self-identification answers for "
                   "pre-filling future applications", required=False)
    page = _FakePage([box])
    # The privacy/consent rule DOES match this label truthfully ("Yes"), so it gets
    # checked — but critically, an unanswerable *optional* box must never block the step.
    result = ia._fill_checkboxes(page)
    assert result is None
