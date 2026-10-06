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
    # Real Cloudflare/Greenhouse label: missed before ("current location"/"which city" didn't
    # match), left blank, and only surfaced as a "submission_unconfirmed" 20s timeout because
    # the resulting inline validation error sat past the old 5,000-char body-search window.
    (_field(label="Location (City)"), "location"),
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
# _fill_text recovery when Playwright reports a control our own extraction
# mis-typed (the real Cloudflare/Greenhouse "Acknowledge/Confirm" consent
# control after a resume-parse re-render: extracted as fillable text, but
# .fill() fails because the live DOM node is actually a checkbox).
# ---------------------------------------------------------------------------

class _FakeLocator:
    def __init__(self, raise_on_fill=None):
        self.raise_on_fill = raise_on_fill
        self.checked = False
        self.filled_value = None

    def fill(self, value):
        if self.raise_on_fill:
            raise self.raise_on_fill
        self.filled_value = value

    def check(self, force=False):
        self.checked = True


class _FakeKeyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


class _FakePage:
    def __init__(self, loc):
        self._loc = loc
        self.keyboard = _FakeKeyboard()
        self.idle_waits = 0
        self.raise_on_idle = None

    def locator(self, _sel):
        return self._loc

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_load_state(self, _state, timeout=0):
        self.idle_waits += 1
        if self.raise_on_idle:
            raise self.raise_on_idle


def test_fill_text_recovers_checkbox_for_a_yes_answer():
    loc = _FakeLocator(raise_on_fill=ats_apply.PWError('Input of type "checkbox" cannot be filled'))
    ats_apply._fill_text(_FakePage(loc), _field(idx=0), "Yes")
    assert loc.checked is True


def test_fill_text_leaves_checkbox_unchecked_for_a_no_answer():
    loc = _FakeLocator(raise_on_fill=ats_apply.PWError('Input of type "checkbox" cannot be filled'))
    ats_apply._fill_text(_FakePage(loc), _field(idx=0), "No")
    assert loc.checked is False


def test_fill_text_reraises_unrelated_playwright_errors():
    loc = _FakeLocator(raise_on_fill=ats_apply.PWError("Some other failure"))
    with pytest.raises(ats_apply.PWError):
        ats_apply._fill_text(_FakePage(loc), _field(idx=0), "Yes")


def test_fill_text_fills_normally_when_no_error():
    loc = _FakeLocator()
    ats_apply._fill_text(_FakePage(loc), _field(idx=0), "Saral Banker")
    assert loc.filled_value == "Saral Banker"


# ---------------------------------------------------------------------------
# _settle — blur + bounded network-idle wait after each field, added for the real
# Snowflake/Ashby race (its own validation banner listed fields as missing that our
# fill had already visibly set — most likely submitted before Ashby's debounced
# client-side validation caught up).
# ---------------------------------------------------------------------------

def test_settle_presses_tab_and_waits_for_network_idle():
    page = _FakePage(_FakeLocator())
    ats_apply._settle(page)
    assert page.keyboard.pressed == ["Tab"]
    assert page.idle_waits == 1


def test_settle_tolerates_a_page_that_never_idles():
    page = _FakePage(_FakeLocator())
    page.raise_on_idle = ats_apply.PWTimeoutError("networkidle timeout")
    ats_apply._settle(page)  # must not raise
    assert page.keyboard.pressed == ["Tab"]


# ---------------------------------------------------------------------------
# _fill_choice on a Greenhouse consent checkbox whose Yes/No labels came from
# the schema merge (idx=None: one real DOM checkbox, not a react-select) — the
# real Cloudflare "Acknowledge/Confirm — Candidate Privacy Policy" question.
# ---------------------------------------------------------------------------

class _FakeIndexedPage:
    """page.locator(sel) returns the same fake for every idx — good enough here since
    _fill_choice's checkbox branch always targets field['idx'], never an option idx."""
    def __init__(self):
        self.loc = _FakeLocator()

    def locator(self, _sel):
        return self.loc


def _schema_checkbox_field(**kw):
    base = _field(idx=7, type="checkbox", label="Acknowledge/Confirm — Candidate Privacy Policy",
                  options=[{"text": "Yes", "idx": None}, {"text": "No", "idx": None}], choice=True)
    base.update(kw)
    return base


def test_fill_choice_checks_schema_checkbox_for_yes():
    page = _FakeIndexedPage()
    assert ats_apply._fill_choice(page, _schema_checkbox_field(), "Yes") is True
    assert page.loc.checked is True


def test_fill_choice_does_not_check_schema_checkbox_for_no():
    page = _FakeIndexedPage()
    assert ats_apply._fill_choice(page, _schema_checkbox_field(), "No") is True
    assert page.loc.checked is False


# ---------------------------------------------------------------------------
# Success / captcha / closed / validation-error detection on HTML fixtures
# ---------------------------------------------------------------------------

def test_success_text_detected_on_confirmation_fixture():
    body = _load("success.html")
    assert ats_apply.SUCCESS_TEXT.search(body)
    assert not ats_apply.CLOSED_TEXT.search(body)


def test_validation_error_past_5000_chars_is_still_detected():
    # Real bug: a long job posting (Cloudflare's runs well past 20,000 chars once the form
    # itself is included) pushed an inline "Please enter your location" validation error
    # past a hardcoded 5,000-char search window in _submit's polling loop, so a genuinely
    # rejected submission was recorded as merely "unconfirmed" instead of a form error.
    padding = "Lorem ipsum dolor sit amet. " * 400  # ~11,200 chars of filler
    assert len(padding) > 10000
    body = padding + "Please enter your location"
    assert not ats_apply.VALIDATION_ERROR_TEXT.search(body[:5000])  # the old, buggy window
    assert ats_apply.VALIDATION_ERROR_TEXT.search(body)             # the fixed, full body


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


def test_validation_error_text_ignores_greenhouse_static_boilerplate():
    # Real bug: every Greenhouse form shows "* indicates a required field" before any
    # field is even touched. Before this fix, that static instructional text alone made
    # _submit() report a real Cloudflare submission as a validation error on the very
    # first poll — regardless of whether anything was actually wrong.
    assert not ats_apply.VALIDATION_ERROR_TEXT.search("* indicates a required field")
    assert not ats_apply.VALIDATION_ERROR_TEXT.search("Fields marked with * indicates an required field")
    # A real per-field error must still be caught.
    assert ats_apply.VALIDATION_ERROR_TEXT.search("Location (City) is a required field")
    assert ats_apply.VALIDATION_ERROR_TEXT.search("Email is required")


# ---------------------------------------------------------------------------
# _new_match — baseline-diffing so static instructional copy already on the page
# before Submit is clicked (Greenhouse's own, and a real Ashby/Snowflake one) is
# never mistaken for a validation error or OTP prompt the submit itself caused.
# ---------------------------------------------------------------------------

def test_new_match_ignores_a_phrase_already_present_before_submit():
    # Real Snowflake/Ashby bug: some static "Please enter..." helper copy was already on the
    # page before Submit was even clicked, and a fully-valid submission was misclassified as
    # a validation error purely because that boilerplate matched the same generic pattern.
    baseline = "Additional notes: please enter details in the box above if needed."
    body = baseline  # unchanged after clicking submit — nothing new appeared
    assert ats_apply._new_match(ats_apply.VALIDATION_ERROR_TEXT, body, baseline) is None


def test_new_match_still_catches_a_genuinely_new_error_reusing_a_generic_word():
    # The opposite mistake would be just as bad: suppressing a real new error because it
    # happens to reuse a common word ("please enter") also used elsewhere on the page.
    baseline = "Additional notes: please enter details in the box above if needed."
    body = baseline + " Location (City): please enter a value."
    match = ats_apply._new_match(ats_apply.VALIDATION_ERROR_TEXT, body, baseline)
    assert match is not None and "please enter" in match.group(0).lower()


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
    ("blocked_antibot:403 https://api.ashbyhq.com/x: spam", S.BLOCKED_ANTIBOT),
    ("otp_required:verification code was sent to saralbanker1@gmail.com", S.OTP_REQUIRED),
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


def test_blocked_antibot_result_carries_the_signal_in_detail():
    result = ats_apply._result_for_error(
        "blocked_antibot:403 https://api.ashbyhq.com/api/non-user-graphql: marked as spam",
        screenshot="shot.png")
    assert result.state == S.BLOCKED_ANTIBOT
    assert "spam" in result.detail
    assert result.screenshot == "shot.png"


# ---------------------------------------------------------------------------
# Email-verification-code gate (EMAIL_OTP_TEXT) — the real Cloudflare/Greenhouse
# challenge this project ran into live: a fully-valid submit was held pending a
# 6-8 character code emailed to the candidate, and OTP_REQUIRED (not a generic
# unconfirmed submission) is the honest, retryable state for it.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    "A verification code was sent to saralbanker1@gmail.com. To submit your application, "
    "enter the 8-character code to confirm you're a human.",
    "We've sent a security code to your email — enter it below to confirm.",
    "Check your inbox for a code and enter it here.",
])
def test_email_otp_text_detects_the_verification_gate(body):
    assert ats_apply.EMAIL_OTP_TEXT.search(body)


def test_email_otp_result_maps_to_otp_required_with_prompt_in_detail():
    result = ats_apply._result_for_error(
        "otp_required:verification code was sent to saralbanker1@gmail.com", screenshot="shot.png")
    assert result.state == S.OTP_REQUIRED
    assert "verification code" in result.detail
    assert result.state in S.RETRYABLE  # a future run should try again, not give up permanently


# ---------------------------------------------------------------------------
# Bot-risk response classification (ANTIBOT_RESPONSE_RE) — the signal that
# distinguishes a silent anti-bot rejection from a generic network/form failure.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    "Your application was flagged as spam and could not be submitted.",
    '{"errors":[{"message":"recaptcha verification failed"}]}',
    "This submission failed our automated bot check.",
    "Request blocked: suspicious activity detected on this session.",
])
def test_antibot_response_re_matches_known_blocker_signals(body):
    assert ats_apply.ANTIBOT_RESPONSE_RE.search(body)


@pytest.mark.parametrize("body", [
    "Email is required",
    "Something went wrong, please try again later.",
    "",
])
def test_antibot_response_re_does_not_match_ordinary_errors(body):
    assert not ats_apply.ANTIBOT_RESPONSE_RE.search(body)


def test_antibot_response_re_matches_the_real_ashby_spam_banner():
    # Verbatim text from a real Ashby/Notion rejection: "flagged as spam" (no words in
    # between) was in ANTIBOT_RESPONSE_RE already, but Ashby's actual wording inserts
    # "possible" — a near-miss that would have left this exact live block undetected.
    assert ats_apply.ANTIBOT_RESPONSE_RE.search(
        "We couldn't submit your application. Your application submission was flagged as "
        "possible spam. If you believe this was a mistake, please submit your application again.")


def test_page_body_spam_banner_is_new_relative_to_baseline():
    # The Ashby spam banner is a PAGE banner, not a failed network response (its GraphQL
    # mutation still answers 200 OK) — _watch_submit_responses alone never sees it, so
    # _submit's page-body check (via _new_match) is what has to catch it.
    baseline = "Software Engineer, Model Capabilities\nFull Name*\nEmail*"
    body = ("We couldn't submit your application. Your application submission was flagged as "
            "possible spam. If you believe this was a mistake, please submit your application "
            "again.\n" + baseline)
    match = ats_apply._new_match(ats_apply.ANTIBOT_RESPONSE_RE, body, baseline)
    assert match is not None  # the exact phrase matched doesn't matter; that it fired does


def test_run_ats_apply_rejects_unsupported_channel():
    job = {"ats_meta": '{"ats": "workable", "apply_url": "https://x"}'}
    result = ats_apply.run_ats_apply(job, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FAILED
    assert "unsupported" in result.detail.lower()


def test_run_ats_apply_rejects_missing_apply_url():
    job = {"ats_meta": '{"ats": "greenhouse"}'}
    result = ats_apply.run_ats_apply(job, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FAILED


# ---------------------------------------------------------------------------
# run_ats_apply's outer exception handler (Phase 9 audit, checklist item 11,
# bounded execution): a hung/erroring browser call — Playwright timeout,
# a generic Playwright error, or an unexpected Chrome crash — must land on
# a terminal/retryable ApplyResult, not raise and leave the attempt stuck.
# `_launch` is monkeypatched to simulate each failure; no real browser is
# ever started.
# ---------------------------------------------------------------------------

_VALID_JOB = {"ats_meta": '{"ats": "greenhouse", "apply_url": "https://boards.greenhouse.io/x/jobs/1"}'}


def test_run_ats_apply_playwright_timeout_maps_to_network_error(monkeypatch):
    monkeypatch.setattr(ats_apply, "_launch", lambda pw: (_ for _ in ()).throw(
        ats_apply.PWTimeoutError("Timeout 30000ms exceeded")))
    result = ats_apply.run_ats_apply(_VALID_JOB, "cover", "resume.pdf", "shot.png")
    assert result.state == S.NETWORK_ERROR
    assert "timeout" in result.detail.lower()


def test_run_ats_apply_playwright_network_error_maps_to_network_error(monkeypatch):
    monkeypatch.setattr(ats_apply, "_launch", lambda pw: (_ for _ in ()).throw(
        ats_apply.PWError("net::ERR_CONNECTION_RESET at https://boards.greenhouse.io/x")))
    result = ats_apply.run_ats_apply(_VALID_JOB, "cover", "resume.pdf", "shot.png")
    assert result.state == S.NETWORK_ERROR


def test_run_ats_apply_playwright_non_network_error_maps_to_failed(monkeypatch):
    monkeypatch.setattr(ats_apply, "_launch", lambda pw: (_ for _ in ()).throw(
        ats_apply.PWError("Target page, context or browser has been closed")))
    result = ats_apply.run_ats_apply(_VALID_JOB, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FAILED
    assert result.detail.startswith("browser_error:")


def test_run_ats_apply_unexpected_crash_maps_to_failed_not_raised(monkeypatch):
    """A raw Chrome/Playwright crash (neither PWTimeoutError nor PWError) must still be
    caught and reported, never propagated out of run_ats_apply."""
    monkeypatch.setattr(ats_apply, "_launch", lambda pw: (_ for _ in ()).throw(
        RuntimeError("chrome crashed unexpectedly")))
    result = ats_apply.run_ats_apply(_VALID_JOB, "cover", "resume.pdf", "shot.png")
    assert result.state == S.FAILED
    assert "chrome crashed" in result.detail
