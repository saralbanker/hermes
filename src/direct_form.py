"""
direct_form.py — Generic engine for direct company-career-page application forms.

    run_direct_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False)
        -> states.ApplyResult

For jobs whose apply target is neither Indeed nor a known ATS (Greenhouse/Lever/Ashby):
a company's own hand-rolled career-site form, reached either directly or via
redirect_resolver when an aggregator (Himalayas, Remotive, RemoteOK) links out to one
with no recognized ATS underneath (apply.py sets job["direct_apply_url"] in that case).

Deliberately reuses ats_apply.py's field extraction/classification/filling
(_extract_fields, _fill_all, _submit, _result_for_error, _screenshot,
_captcha_challenge_visible, CLOSED_TEXT) instead of re-implementing it: a hand-rolled
company form asks the same kinds of questions (name, email, phone, location, LinkedIn,
GitHub, portfolio, resume, cover letter, work authorization, notice period, salary,
years of experience, EEO/pronoun decline) that answers.answer_question() and
ats_apply._answer_for()/_classify() already map deterministically, with the local LLM
used only for open-ended text and never for a required field with no truthful answer.

What is different from a hosted-ATS form:
 - No ATS API schema to merge in (ats_apply._merge_greenhouse has no equivalent here).
 - Cookie-consent banners are common on a company's own domain and are dismissed before
   every field scan.
 - Multi-step "Next" wizards without a page navigation between steps (_drive_steps loops
   fill -> Next until a real Submit control appears, unlike ats_apply's single-page form).
 - A login wall or "create an account to apply" wall is detected and named explicitly
   (FORM_CHANGED) rather than attempted — Hermes never creates throwaway accounts.

Internal error codes are ats_apply.py's vocabulary (see its docstring) plus two of our
own: login_wall, account_wall — both mapped to FORM_CHANGED by _map_error below, since
neither is fixable by retrying and neither is the Indeed-specific "our session expired"
case that LOGIN_REQUIRED means elsewhere in this codebase.
"""
from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import states
from ats_apply import (
    CLOSED_TEXT,
    SUCCESS_TEXT,
    VALIDATION_ERROR_TEXT,
    _captcha_challenge_visible,
    _extract_fields,
    _fill_all,
    _result_for_error,
    _screenshot,
)
from display import ensure_virtual_display

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover — pure functions (used by tests) must import fine either way
    sync_playwright = None
    PWTimeoutError = PWError = Exception

ROOT = Path(__file__).parent.parent
PROFILE_DIR = ROOT / "output" / "chrome-direct-profile"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/142.0.0.0 Safari/537.36"
)
MAX_STEPS = 8
MAX_APPLY_SECONDS = 6 * 60

# Broader than ats_apply._submit's own selector on purpose: some ATS vendors label their
# final button "Send" rather than "Submit" (verified live: Recruitee's application form,
# a plain "Send" button with no "Submit" text anywhere). ats_apply._submit itself is left
# untouched — Greenhouse/Lever/Ashby all say "Submit" — so _submit_direct below duplicates
# its small click+classify loop with this wider match instead of broadening the shared one.
FINAL_SELECTOR = ('button[type="submit"]:has-text("Submit"), button:has-text("Submit application"), '
                  '#btn-submit, button:has-text("Submit Application"), '
                  'button:has-text("Send"), button:has-text("Send application"), '
                  'button:has-text("Send my application")')
NEXT_RE = re.compile(r"^(next|continue|proceed( to next step)?)\b", re.I)
COOKIE_ACCEPT_RE = re.compile(
    r"^(accept all( cookies)?|allow all( cookies)?|i agree|i accept|got it|agree( and continue)?)$", re.I)
LOGIN_WALL_RE = re.compile(r"log ?in to (apply|continue)|sign in to (apply|continue)|please (log|sign) in to",
                           re.I)
ACCOUNT_WALL_RE = re.compile(
    r"create an account|sign up to apply|register to apply|create your account to apply", re.I)


# ---------------------------------------------------------------------------
# Browser lifecycle
# ---------------------------------------------------------------------------

def _launch(pw):
    ensure_virtual_display()  # headful Chrome inside a private Xvfb display — see display.py
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        viewport={"width": 1366, "height": 900},
        user_agent=USER_AGENT,
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        args=["--disable-blink-features=AutomationControlled"],
    )


def _dismiss_cookies(page) -> None:
    """OneTrust/Cookiebot-style banners are common on a company's own domain and can hide
    the real form/Next button underneath. Clicking Accept (never Reject, which can disable
    functional cookies the form needs) is ordinary consent handling, not an anti-bot
    bypass. Best-effort and silent on absence — most pages have no banner at all."""
    try:
        buttons = page.locator("button:visible, [role=button]:visible")
        for i in range(min(buttons.count(), 25)):
            text = (buttons.nth(i).inner_text(timeout=200) or "").strip()
            if COOKIE_ACCEPT_RE.match(text):
                buttons.nth(i).click(timeout=1500)
                page.wait_for_timeout(400)
                return
    except Exception:  # never let banner handling break the real form fill
        pass


# ---------------------------------------------------------------------------
# Page-state detection
# ---------------------------------------------------------------------------

def _wall_state(page) -> str | None:
    """captcha_blocked | login_wall | account_wall | posting_closed | None (a normal form)."""
    if _captcha_challenge_visible(page):
        return "captcha_blocked"
    try:
        body = page.inner_text("body")[:4000]
    except Exception:  # mid-navigation — treated as a normal form; the next loop tick recheck
        return None
    if page.locator('input[type="password"]').count() and LOGIN_WALL_RE.search(body):
        return "login_wall"
    if ACCOUNT_WALL_RE.search(body):
        return "account_wall"
    if CLOSED_TEXT.search(body):
        return "posting_closed"
    return None


def _click_next(page) -> bool:
    buttons = page.locator("button:visible, [role=button]:visible")
    for i in range(min(buttons.count(), 40)):
        b = buttons.nth(i)
        try:
            text = (b.inner_text(timeout=300) or "").strip()
        except Exception:
            continue
        if NEXT_RE.match(text):
            try:
                b.click(timeout=3000)
            except Exception:
                return False
            page.wait_for_timeout(1200)
            return True
    return False


# Workable/SmartRecruiters/Recruitee (and most hand-rolled career pages) show a job
# DESCRIPTION first, with the actual name/email/resume form reached only after clicking
# an "Apply"/"Apply Now" button — verified live against real apply.workable.com,
# jobs.smartrecruiters.com and *.recruitee.com postings, all of which extract zero fields
# until this is clicked. Distinct from _click_next: this is the one-time entry click, not
# a later wizard step, and matches on the whole label, not just its start ("Apply for this
# job" would not match a "^apply\b"-only pattern's intent to also catch a bare "Apply").
APPLY_ENTRY_RE = re.compile(
    r"^(apply( now| for this job| to this job)?|start application|i'?m interested)$", re.I)


def _click_apply_entry(page) -> bool:
    buttons = page.locator("button:visible, [role=button]:visible, a:visible")
    for i in range(min(buttons.count(), 40)):
        b = buttons.nth(i)
        try:
            text = (b.inner_text(timeout=300) or "").strip()
        except Exception:
            continue
        if APPLY_ENTRY_RE.match(text):
            try:
                b.click(timeout=3000)
            except Exception:
                continue
            # This click can be a full page navigation to a JS-heavy apply form (verified
            # live: SmartRecruiters' "oneclick-ui" form, shadow-DOM web components took
            # longer than 1.5s to render — 0 fields were extracted with a shorter wait
            # even though the form had fully loaded moments later). A flat, generous delay
            # proved more reliable live than wait_for_load_state("networkidle"), which some
            # ATS pages (Workable: persistent analytics/keep-alive traffic) never satisfy.
            page.wait_for_timeout(3000)
            return True
    return False


def _submit_direct(page) -> tuple[str | None, str | None]:
    """Click the final Submit/Send button and classify the outcome — same shape and
    polling logic as ats_apply._submit, just with FINAL_SELECTOR's wider button match
    (see its comment above). Returns (error_code, evidence); error_code is None with
    evidence set on success."""
    button = page.locator(FINAL_SELECTOR).last
    if not button.count():
        return "form_not_submitted", None
    start_url = page.url
    try:
        button.click()
    except PWTimeoutError as exc:
        return f"network_error:{str(exc)[:150]}", None
    for _ in range(20):  # up to ~20 s for confirmation
        page.wait_for_timeout(1000)
        try:
            body = page.inner_text("body")[:5000]
        except Exception:  # page mid-navigation — try again next tick
            body = ""
        match = SUCCESS_TEXT.search(body)
        if match:
            return None, match.group(0)
        if page.url != start_url and re.search(r"confirmation|thank|success", page.url, re.I):
            return None, page.url
        if _captcha_challenge_visible(page):
            return "captcha_blocked", None
        err = VALIDATION_ERROR_TEXT.search(body)
        if err:
            return f"validation_error:{err.group(0)}", None
    return "unconfirmed", None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _open(page, url: str) -> str | None:
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PWTimeoutError as exc:
        return f"network_error:{str(exc)[:150]}"
    if response is not None and response.status in (404, 410):
        return "posting_closed"
    page.wait_for_timeout(3000)
    _dismiss_cookies(page)
    return _wall_state(page)


def _drive_steps(page, cover_letter: str, resume_path: str, cover_path: str,
                  dry_run: bool, deadline: float) -> tuple[str | None, str | None]:
    """Fill/advance through however many steps the form has. Returns (error_code,
    evidence) in ats_apply's vocabulary, or ("dry_run_ok", None)."""
    for _ in range(MAX_STEPS):
        if time.monotonic() > deadline:
            return "network_error:exceeded apply time budget", None
        _dismiss_cookies(page)
        wall = _wall_state(page)
        if wall:
            return wall, None
        fields = _extract_fields(page)
        if not fields and _click_apply_entry(page):
            # Description-first career pages (Workable, SmartRecruiters, Recruitee, ...)
            # reveal the actual form only after this click — re-scan once before failing.
            _dismiss_cookies(page)
            fields = _extract_fields(page)
        if not fields:
            return "form_missing_fields", None
        error = _fill_all(page, fields, cover_letter, resume_path, cover_path)
        if error:
            return error, None
        if page.locator(FINAL_SELECTOR).count():
            if dry_run:
                return "dry_run_ok", None
            return _submit_direct(page)
        if _click_next(page):
            continue
        return "form_not_submitted", None
    return "unconfirmed", None


def _map_error(code: str, screenshot: str | None) -> states.ApplyResult:
    """direct_form-specific codes first, then ats_apply's shared vocabulary."""
    if code == "login_wall":
        return states.ApplyResult(states.FORM_CHANGED,
                                  detail="application requires logging into an existing account on this site",
                                  screenshot=screenshot)
    if code == "account_wall":
        return states.ApplyResult(states.FORM_CHANGED,
                                  detail="application requires creating a new account on this site",
                                  screenshot=screenshot)
    if code == "form_not_submitted":
        # Distinct from ats_apply's meaning (a single-page form's Submit button vanished):
        # here it means no Next/Submit control was ever found on this step at all.
        return states.ApplyResult(states.FORM_CHANGED, detail="no Next/Submit control found on this step",
                                  screenshot=screenshot)
    return _result_for_error(code, screenshot)


def run_direct_apply(job: dict, cover_letter: str, resume_path: str, screenshot_path: str,
                     dry_run: bool = False) -> states.ApplyResult:
    url = job.get("direct_apply_url") or job.get("url")
    if not url:
        return states.ApplyResult(states.FORM_CHANGED, detail="no direct apply URL to open")
    cover_dir = Path(tempfile.mkdtemp(prefix="hermes-direct-"))
    cover_path = str(cover_dir / "Saral_Banker_Cover_Letter.txt")
    Path(cover_path).write_text(cover_letter or "", encoding="utf-8")
    try:
        with sync_playwright() as pw:
            ctx = _launch(pw)
            try:
                return _apply_in_browser(ctx, url, cover_letter, resume_path, cover_path,
                                         screenshot_path, dry_run)
            finally:
                ctx.close()
    except PWTimeoutError as exc:
        return states.ApplyResult(states.NETWORK_ERROR, detail=f"timeout: {str(exc)[:200]}")
    except PWError as exc:
        msg = str(exc)
        if re.search(r"net::ERR_|timeout|ECONNRESET|ENOTFOUND|dns", msg, re.IGNORECASE):
            return states.ApplyResult(states.NETWORK_ERROR, detail=msg[:200])
        return states.ApplyResult(states.FAILED, detail=f"browser_error:{msg[:200]}")
    except Exception as exc:  # Playwright/Chrome crash: report it, pipeline continues
        return states.ApplyResult(states.FAILED, detail=f"browser_error:{str(exc)[:200]}")
    finally:
        Path(cover_path).unlink(missing_ok=True)
        cover_dir.rmdir()


def _apply_in_browser(ctx, url: str, cover_letter: str, resume_path: str, cover_path: str,
                      screenshot_path: str, dry_run: bool) -> states.ApplyResult:
    page = ctx.new_page()
    error = _open(page, url)
    if error:
        return _map_error(error, _screenshot(page, screenshot_path))
    deadline = time.monotonic() + MAX_APPLY_SECONDS
    error, evidence = _drive_steps(page, cover_letter, resume_path, cover_path, dry_run, deadline)
    if error == "dry_run_ok":
        return states.ApplyResult(states.DRY_RUN_OK, detail="all fields filled, submit deliberately skipped",
                                  screenshot=_screenshot(page, screenshot_path))
    if error:
        return _map_error(error, _screenshot(page, screenshot_path))
    return states.ApplyResult(states.SUBMITTED, detail="application submitted",
                              screenshot=_screenshot(page, screenshot_path), evidence=evidence or page.url)
