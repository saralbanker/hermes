"""Offline tests for the ATS applier: URL classification, field classification,
and outcome detection (success/captcha/closed/validation-error) on HTML fixtures.

No network, no browser — nothing here launches Playwright or DrissionPage.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import ats_apply
import states as S
from redirect_resolver import ats_from_url, describe_host

FIXTURES = Path(__file__).parent / "fixtures" / "ats"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# ats_from_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,ats,token,job_id", [
    ("https://boards.greenhouse.io/stripe/jobs/7764109003", "greenhouse", "stripe", "7764109003"),
    ("https://job-boards.greenhouse.io/affirm/jobs/7764109003", "greenhouse", "affirm", "7764109003"),
    ("https://boards.eu.greenhouse.io/algolia/jobs/6008981004", "greenhouse", "algolia", "6008981004"),
    ("https://job-boards.greenhouse.io/embed/job_app?for=amplitude&token=8647263002",
     "greenhouse", "amplitude", "8647263002"),
    # "company site" convention: TOKEN acts as the company's own board, job selected via ?gh_jid=
    ("https://boards.greenhouse.io/affirm?gh_jid=7764109003", "greenhouse", "affirm", "7764109003"),
    ("https://jobs.lever.co/contentsquare/fc030034-3050-4b3a-9b79-380dd0f5a0f6",
     "lever", "contentsquare", "fc030034-3050-4b3a-9b79-380dd0f5a0f6"),
    ("https://jobs.ashbyhq.com/1password/6f78b170-9600-4b2d-9682-feead160100d",
     "ashby", "1password", "6f78b170-9600-4b2d-9682-feead160100d"),
])
def test_ats_from_url_recognizes_supported_boards(url, ats, token, job_id):
    result = ats_from_url(url)
    assert result is not None
    channel, meta_json = result
    assert channel == ats
    import json
    meta = json.loads(meta_json)
    assert meta["ats"] == ats
    assert meta["token"] == token
    assert meta["job_id"] == job_id
    assert meta["apply_url"].startswith("https://")


@pytest.mark.parametrize("url", [
    None,
    "",
    "https://careers.airbnb.com/positions/8214444?gh_jid=8214444",  # token unrecoverable from URL alone
    "https://apply.workable.com/acme/j/ABCDEF123/",
    "https://example.com/jobs/123",
])
def test_ats_from_url_returns_none_for_unsupported(url):
    assert ats_from_url(url) is None


def test_describe_host_flags_gh_jid_on_unknown_domain():
    hint = describe_host("https://careers.airbnb.com/positions/8214444?gh_jid=8214444")
    assert "airbnb.com" in hint
    assert "board token unknown" in hint


# ---------------------------------------------------------------------------
# Field classification (_classify) — shape matches ats_extract.js output
# ---------------------------------------------------------------------------

def _field(**kw) -> dict:
    base = {"idx": 0, "tag": "INPUT", "type": "text", "label": "", "required": False,
            "prefilled": False, "options": [], "name": "", "id": "", "combobox": False}
    base.update(kw)
    return base


@pytest.mark.parametrize("field,expected", [
    (_field(type="file", label="Resume/CV", name="resume"), "resume"),
    (_field(type="file", label="Cover Letter", name="cover_letter"), "cover_file"),
    (_field(tag="TEXTAREA", label="Cover Letter"), "cover_text"),
    (_field(tag="TEXTAREA", label="Why do you want to work here?"), "cover_text"),
    (_field(tag="TEXTAREA", label="Additional Information"), "cover_text"),
    (_field(label="Current location", id="candidate-location"), "location"),
    (_field(label="Current company"), "company"),
    (_field(label="Gender", options=[{"text": "Male", "idx": 1}, {"text": "Decline to self-identify", "idx": 2}]),
     "eeo"),
    (_field(label="Degree", combobox=True, options=[]), "degree"),
    (_field(label="End Date Year"), "edu_year"),
    (_field(label="Start Date Year"), "edu_year"),
    (_field(label="LinkedIn URL"), "generic"),
    (_field(type="file", label="Portfolio (optional)", name="portfolio"), "skip"),
])
def test_classify(field, expected):
    assert ats_apply._classify(field) == expected


def test_eeo_decline_option_is_selected_deterministically():
    field = _field(label="Gender", options=[
        {"text": "Male", "idx": 1}, {"text": "Female", "idx": 2},
        {"text": "Decline to self-identify", "idx": 3},
    ])
    answer = ats_apply._answer_for(field, cover_letter="dummy cover letter")
    assert answer == "Decline to self-identify"


def test_ai_policy_certification_is_left_unanswered():
    field = _field(tag="TEXTAREA", label="I certify this application was written without the use of AI")
    assert ats_apply._answer_for(field, cover_letter="dummy") is None


def test_notice_period_picks_shortest_truthful_bucket():
    field = _field(label="When can you start?", options=[
        {"text": "Immediately", "idx": 1}, {"text": "2 weeks", "idx": 2}, {"text": "1 month+", "idx": 3},
    ])
    assert ats_apply._answer_for(field, cover_letter="dummy") == "Immediately"


# ---------------------------------------------------------------------------
# Success / captcha / closed / validation-error detection on HTML fixtures
# ---------------------------------------------------------------------------

def test_success_text_detected_on_confirmation_fixture():
    body = _load("success.html")
    assert ats_apply.SUCCESS_TEXT.search(body)
    assert not ats_apply.CLOSED_TEXT.search(body)


def test_captcha_iframe_detected_on_captcha_fixture():
    html = _load("captcha.html")
    srcs = re.findall(r'src="([^"]+)"', html)
    assert any(ats_apply.CAPTCHA_FRAME_RE.search(s) for s in srcs)
    assert not ats_apply.SUCCESS_TEXT.search(html)


def test_closed_text_detected_on_closed_fixture():
    body = _load("closed.html")
    assert ats_apply.CLOSED_TEXT.search(body)
    assert not ats_apply.SUCCESS_TEXT.search(body)


def test_validation_error_text_detected_on_validation_fixture():
    body = _load("validation_error.html")
    assert ats_apply.VALIDATION_ERROR_TEXT.search(body)
    assert not ats_apply.SUCCESS_TEXT.search(body)


def test_success_fixture_has_no_captcha_markers():
    html = _load("success.html")
    srcs = re.findall(r'src="([^"]+)"', html)
    assert not any(ats_apply.CAPTCHA_FRAME_RE.search(s) for s in srcs)


# ---------------------------------------------------------------------------
# Error code -> ApplyResult mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected_state", [
    ("posting_closed", S.EXPIRED),
    ("captcha_blocked", S.CAPTCHA_REQUIRED),
    ("form_missing_fields", S.FORM_CHANGED),
    ("unanswerable:Are you willing to relocate?", S.FORM_CHANGED),
    ("validation_error:Email is required", S.FORM_CHANGED),
    ("form_not_submitted", S.FAILED),
    ("unconfirmed", S.SUBMISSION_UNCONFIRMED),
    ("unsupported_ats", S.FAILED),
    ("network_error:timeout", S.NETWORK_ERROR),
    ("something_unexpected", S.FAILED),
])
def test_result_for_error_maps_to_expected_state(code, expected_state):
    result = ats_apply._result_for_error(code, screenshot=None)
    assert result.state == expected_state
    assert isinstance(result, S.ApplyResult)


def test_run_ats_apply_rejects_unsupported_channel():
    job = {"ats_meta": '{"ats": "workable", "apply_url": "https://x"}'}
    result = ats_apply.run_ats_apply(job, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FAILED
    assert "unsupported" in result.detail.lower()


def test_run_ats_apply_rejects_missing_apply_url():
    job = {"ats_meta": '{"ats": "greenhouse"}'}
    result = ats_apply.run_ats_apply(job, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FAILED
