"""
indeed_apply.py — Apply to Indeed jobs with DrissionPage, headful Chrome under Xvfb.

    run_indeed_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False)
        -> states.ApplyResult

Cloudflare blocks headless Chrome on Indeed's viewjob/smartapply pages (verified),
so this module always launches headful Chrome. display.ensure_virtual_display()
is called first so that window renders in a private Xvfb display instead of the
real (Wayland) desktop. The browser uses a persistent profile
(output/chrome-indeed-profile) so cookies accumulate across runs; if that profile
has no Indeed session yet, cookies are seeded once from output/indeed_session.json.

classify_page(url, title, text, html) is a PURE function — no browser, no I/O —
that reads multiple independent signals (URL host/path, page title, Cloudflare
challenge markers, hCaptcha/reCAPTCHA markers, password-field presence, and
phrase matches) to name the kind of page Indeed just served. Keeping it pure
means it can be exhaustively unit-tested (tests/test_indeed_classify.py) without
a browser, which is how the previous version's "853 Cloudflare pages misread as
login walls" bug (matching on the word "Sign in" alone, present in every Indeed
header) is prevented from recurring.

Screening questions are answered exclusively through answers.answer_question —
this file has no LLM-calling code of its own. A required question with no
truthful answer aborts the application as FORM_CHANGED; nothing is ever guessed.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import states
from answers import answer_question
from display import ensure_virtual_display
from states import ApplyResult

ROOT = Path(__file__).parent.parent
PROFILE_DIR = ROOT / "output" / "chrome-indeed-profile"
COOKIES_PATH = ROOT / "output" / "indeed_session.json"

MAX_APPLY_SECONDS = 6 * 60          # whole application, hard budget
INTERSTITIAL_WAIT_SECONDS = 20      # let a non-interactive Cloudflare check clear itself
NAV_TIMEOUT = 30
ELE_TIMEOUT = 4
MAX_FORM_STEPS = 12

# ---------------------------------------------------------------------------
# classify_page() signal patterns — pure, no page/browser access below this point.
# ---------------------------------------------------------------------------

_CF_TITLE_RE = re.compile(r"just a moment|attention required", re.I)
_CF_MARKER_RE = re.compile(
    r"cf-chl|challenge-platform|cf_chl_opt|cdn-cgi/challenge|jschl-answer|"
    r"turnstile|checking your browser before accessing|cf-browser-verification",
    re.I,
)

_LOGIN_URL_RE = re.compile(r"secure\.indeed\.com/(auth|account/login)", re.I)
_PASSWORD_FIELD_RE = re.compile(r'<input[^>]+type=["\']password["\']', re.I)
_LOGIN_PHRASE_RE = re.compile(r"sign in to (your|continue)|welcome back|forgot.{0,10}password", re.I)
_EMAIL_FIELD_RE = re.compile(r'<input[^>]+type=["\']email["\']', re.I)

# A visible challenge is an iframe/widget, not the passive scripts every page loads.
_CAPTCHA_RE = re.compile(
    r"<iframe[^>]+src=[\"'][^\"']*(hcaptcha\.com|recaptcha/api2?/(anchor|bframe)|challenges\.cloudflare\.com)",
    re.I,
)
_OTP_INPUT_RE = re.compile(
    r'<input[^>]+(autocomplete=["\']one-time-code|name=["\'][^"\']*(otp|passcode|code)["\']|'
    r'inputmode=["\']numeric)', re.I)
_OTP_URL_RE = re.compile(r"otp|passcode|verify|/auth", re.I)

_OTP_RE = re.compile(
    r"enter the code|verification code|we('| ha)ve sent|sent (you )?a code|security code|"
    r"enter (the )?code|one-time (code|password)|verify your (email|phone|identity)|"
    r"confirm your identity|check your (email|phone|inbox)|enter the 6.digit code",
    re.I,
)
_OTP_EMAIL_CTX_RE = re.compile(r"sent.{0,40}(email|inbox)|check your (email|inbox)|email.{0,20}code", re.I)
_OTP_PHONE_CTX_RE = re.compile(r"sent.{0,40}(phone|text message|sms)|check your (phone|mobile)|phone.{0,20}code", re.I)

_SUCCESS_RE = re.compile(
    r"application (has been )?(sent|submitted|received|complete)|successfully applied|"
    r"thank you for applying|we('| ha)ve received your application|"
    r"your application (has been submitted|is complete)",
    re.I,
)
_ALREADY_APPLIED_RE = re.compile(r"you'?ve applied|you applied on|already applied|applied on [a-z]+ \d", re.I)
_EXPIRED_RE = re.compile(
    r"this job has expired|no longer accepting applications|no longer available|"
    r"job (is )?no longer active|posting has expired|this (job|posting) (is )?closed|"
    r"we can.t find this page|page doesn.t exist or isn.t available",
    re.I,
)

_APPLICATION_URL_RE = re.compile(r"smartapply\.indeed\.com", re.I)
_APPLICATION_MARKER_RE = re.compile(
    r"ia-basepage|ia-continuebutton|ia-applyformscreen|continue to next step|"
    r"submit your application",
    re.I,
)
_JOB_PAGE_MARKER_RE = re.compile(r"/viewjob|jobsearch|jobtitle", re.I)


def classify_page(url: str, title: str, text: str, html: str) -> str:
    """
    Pure classifier: no side effects, no browser access. Returns one of:
    application, login, otp, security_interstitial, captcha, success,
    already_applied, expired, job_page, unknown.

    Order matters: Cloudflare interstitials are checked first because they can
    render arbitrary leftover page chrome (including the header's permanent
    "Sign in" link), which must never be mistaken for an actual login wall.
    """
    url, title, text, html = url or "", title or "", text or "", html or ""
    # Phrase signals are matched on VISIBLE text only: every Indeed page embeds the
    # passive Cloudflare challenge-platform script and i18n strings in its HTML.
    hay = f"{title}\n{text}"

    if _is_interstitial(title, text, html):
        return "security_interstitial"
    if _is_login(url, html, hay):
        return "login"
    if _CAPTCHA_RE.search(html):
        return "captcha"
    if _OTP_RE.search(hay) and (_OTP_INPUT_RE.search(html) or _OTP_URL_RE.search(url)):
        return "otp"
    if _SUCCESS_RE.search(hay):
        return "success"
    if _ALREADY_APPLIED_RE.search(hay):
        return "already_applied"
    if _EXPIRED_RE.search(hay):
        return "expired"
    if _APPLICATION_URL_RE.search(url) or _APPLICATION_MARKER_RE.search(f"{hay}\n{html}"):
        return "application"
    if _JOB_PAGE_MARKER_RE.search(url) or _JOB_PAGE_MARKER_RE.search(html):
        return "job_page"
    return "unknown"


def _is_interstitial(title: str, text: str, html: str) -> bool:
    """Cloudflare's own title, or a challenge marker on a page with almost no content.
    A normal page that merely loads challenge-platform/jsd scripts is not a wall."""
    if _CF_TITLE_RE.search(title):
        return True
    return bool(_CF_MARKER_RE.search(html)) and len(text.strip()) < 600 \
        and not _JOB_PAGE_MARKER_RE.search(html)


def _is_login(url: str, html: str, hay: str) -> bool:
    """A real login wall: URL is the Indeed auth host, OR a password field is on the
    page. The header's "Sign in" LINK (present on every Indeed page, including
    Cloudflare interstitials) never has a password input and must never match here."""
    if _LOGIN_URL_RE.search(url):
        return True
    if _PASSWORD_FIELD_RE.search(html):
        return True
    if _EMAIL_FIELD_RE.search(html) and _LOGIN_PHRASE_RE.search(hay):
        return True
    return False


def _otp_channel(hay: str) -> str:
    """email | phone | unknown, from the page's own wording."""
    if _OTP_EMAIL_CTX_RE.search(hay):
        return "email"
    if _OTP_PHONE_CTX_RE.search(hay):
        return "phone"
    return "unknown"


def _success_evidence(hay: str, url: str) -> str:
    m = _SUCCESS_RE.search(hay)
    return f"{m.group(0)!r} @ {url}" if m else url


# ---------------------------------------------------------------------------
# Browser lifecycle
# ---------------------------------------------------------------------------

def _launch_browser():
    from DrissionPage import ChromiumOptions, ChromiumPage

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.set_user_data_path(str(PROFILE_DIR))
    co.headless(False)  # headful — Cloudflare blocks headless on Indeed viewjob pages
    co.set_argument("--window-size=1366,900")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_pref("credentials_enable_service", False)
    co.set_pref("profile.password_manager_enabled", False)

    page = ChromiumPage(addr_or_opts=co)
    page.set.timeouts(base=ELE_TIMEOUT, page_load=NAV_TIMEOUT, script=15)
    return page


AUTH_COOKIES = {"SHOE", "PPID", "SOCK", "passport_auth_state"}  # present only when signed in


def _seed_session_cookies(page) -> None:
    """Load output/indeed_session.json only if the persistent profile has no
    Indeed cookies of its own yet (first run / profile was wiped)."""
    if not COOKIES_PATH.exists():
        return
    try:
        page.get("https://in.indeed.com", timeout=NAV_TIMEOUT)
    except Exception:
        return
    try:
        names = {c.get("name") for c in page.cookies(all_domains=True)}
        if names & AUTH_COOKIES:
            return  # profile already holds a login — don't overwrite it
    except Exception as exc:  # unreadable cookie jar: fall through and seed
        print(f"  [indeed] cookie read failed ({exc}); seeding saved session")
    try:
        cookies = json.loads(COOKIES_PATH.read_text())
    except Exception:
        return
    failed = 0
    for ck in cookies:
        try:
            page.set.cookies(ck)
        except Exception:  # one malformed cookie must not block the rest; counted below
            failed += 1
    if failed:
        print(f"  [indeed] {failed}/{len(cookies)} saved cookies could not be set")
    page.refresh()


def _screenshot(page, path: str | None) -> str | None:
    if not path:
        return None
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        page.get_screenshot(path=path)
        return path
    except Exception:
        return None


def _snapshot(page) -> tuple[str, str, str, str]:
    """(url, title, text, html) — the four classify_page() inputs, read once."""
    url = ""
    title = ""
    text = ""
    html = ""
    try:
        url = page.url or ""
    except Exception:
        pass
    try:
        title = page.title or ""
    except Exception:
        pass
    try:
        html = page.html or ""
    except Exception:
        pass
    try:
        text = page.ele("tag:body", timeout=1).text or ""
    except Exception:
        pass
    return url, title, text, html


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------

def _handle_otp(page, hay: str) -> str | None:
    """Try to resolve an email OTP. Returns None on success (page moved on),
    or an ApplyResult-state-ready detail string describing why it could not."""
    channel = _otp_channel(hay)
    if channel == "phone":
        return "phone OTP required — never auto-bypassed"

    from otp_resolver import fetch_otp, is_configured

    if not is_configured():
        return "email OTP required but GMAIL_APP_PASSWORD is not configured"

    code = fetch_otp()
    if not code:
        return "email OTP requested but no code arrived within the poll window"

    entered = _enter_otp_code(page, code)
    if not entered:
        return "OTP email arrived but no code input field was found on the page"
    return None


def _enter_otp_code(page, code: str) -> bool:
    for selector in (
        'input[name*="code" i]', 'input[name*="otp" i]', 'input[name*="verify" i]',
        'input[placeholder*="code" i]', 'input[maxlength="6"]',
    ):
        try:
            el = page.ele(f"css:{selector}", timeout=1)
        except Exception:
            continue
        if not el:
            continue
        try:
            el.clear()
            el.input(code)
        except Exception:
            continue
        _click_first(page, ["verify", "submit", "confirm", "continue"])
        time.sleep(2.0)
        return True
    return False


# ---------------------------------------------------------------------------
# Form filling
# ---------------------------------------------------------------------------

def _click_first(page, texts: list[str]) -> bool:
    for text in texts:
        xp = (
            'xpath://button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            f' "abcdefghijklmnopqrstuvwxyz"), "{text.lower()}")] | '
            '//*[@role="button"][contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ",'
            f' "abcdefghijklmnopqrstuvwxyz"), "{text.lower()}")]'
        )
        try:
            btn = page.ele(xp, timeout=1)
        except Exception:
            continue
        if btn:
            try:
                btn.click()
                return True
            except Exception:
                continue
    return False


def _label_for(page, ele) -> str:
    for attr in ("aria-label", "placeholder"):
        try:
            v = ele.attr(attr)
            if v and v.strip():
                return v.strip()
        except Exception:
            pass
    try:
        eid = ele.attr("id")
        if eid:
            lbl = page.ele(f'css:label[for="{eid}"]', timeout=1)
            if lbl and lbl.text.strip():
                return lbl.text.strip()
    except Exception:
        pass
    try:
        p = ele.parent()
        if p and p.text.strip():
            return p.text.strip()[:200]
    except Exception:
        pass
    try:
        return ele.attr("name") or ""
    except Exception:
        return ""


def _is_required(ele) -> bool:
    try:
        if ele.attr("required") is not None or ele.attr("aria-required") == "true":
            return True
    except Exception:
        pass
    try:
        return "*" in (ele.parent().text or "")
    except Exception:
        return False


def _fill_resume(page, resume_path: str) -> None:
    if not resume_path or not Path(resume_path).exists():
        return
    try:
        el = page.ele('css:input[type="file"]', timeout=1)
    except Exception:
        el = None
    if el:
        try:
            el.input(resume_path)
            time.sleep(1.5)
        except Exception:
            pass


def _fill_text_inputs(page, cover_letter: str) -> str | None:
    """Fill visible text/textarea inputs. Returns a FORM_CHANGED detail string
    (naming the question) on the first required field with no truthful answer."""
    try:
        eles = page.eles("css:input[type=text], input[type=tel], input[type=email], "
                          "input:not([type]), textarea", timeout=1)
    except Exception:
        eles = []
    for ele in eles:
        try:
            if ele.value and str(ele.value).strip():
                continue  # already filled (identity fields autofilled by Indeed profile)
        except Exception:
            pass
        label = _label_for(page, ele)
        if not label:
            continue
        is_cover = ele.tag == "textarea" and re.search(r"cover|why|motivat|tell us", label, re.I)
        value = cover_letter if (is_cover and cover_letter) else answer_question(
            label, kind="textarea" if ele.tag == "textarea" else "text"
        )
        if value:
            try:
                ele.input(value[:2000])
            except Exception:
                pass
        elif _is_required(ele):
            return label
    return None


def _fill_selects(page) -> str | None:
    try:
        selects = page.eles("css:select", timeout=1)
    except Exception:
        selects = []
    for sel in selects:
        try:
            if sel.value:
                continue
        except Exception:
            pass
        label = _label_for(page, sel)
        try:
            options = [o.text.strip() for o in sel.eles("tag:option") if o.text.strip()]
        except Exception:
            options = []
        options = [o for o in options if o.lower() not in ("select...", "select an option")]
        if not options or not label:
            continue
        answer = answer_question(label, options=options, kind="choice")
        if answer:
            try:
                sel.select.by_text(answer)
            except Exception:
                pass
        elif _is_required(sel):
            return label
    return None


def _fill_radio_groups(page) -> str | None:
    try:
        groups = page.eles('css:fieldset, [role="radiogroup"]', timeout=1)
    except Exception:
        groups = []
    for group in groups:
        try:
            radios = group.eles('css:input[type="radio"]')
        except Exception:
            continue
        if not radios:
            continue
        try:
            if any(r.states.is_checked for r in radios):
                continue
        except Exception:
            pass
        label = _label_for(page, group)
        options, opt_eles = [], []
        for r in radios:
            txt = _label_for(page, r)
            if txt:
                options.append(txt)
                opt_eles.append((txt, r))
        if not options or not label:
            continue
        answer = answer_question(label, options=options, kind="choice")
        if answer:
            match = next((r for t, r in opt_eles if t == answer), None)
            if match:
                try:
                    match.click()
                except Exception:
                    pass
        elif _is_required(group):
            return label
    return None


def _fill_form_step(page, cover_letter: str, resume_path: str) -> str | None:
    """Fill everything visible on the current step. Returns a FORM_CHANGED
    detail string if a required question has no truthful answer, else None."""
    _fill_resume(page, resume_path)
    for filler in (_fill_text_inputs, _fill_selects, _fill_radio_groups):
        args = (page, cover_letter) if filler is _fill_text_inputs else (page,)
        detail = filler(*args)
        if detail:
            return f"unanswerable required question: {detail}"
    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _wait_out_interstitial(page, deadline: float) -> str:
    """Poll up to INTERSTITIAL_WAIT_SECONDS for a Cloudflare check to clear on
    its own. Never clicks or solves anything. Returns the page class once it
    stops being 'security_interstitial' or the wait/overall deadline is hit."""
    give_up = min(deadline, time.monotonic() + INTERSTITIAL_WAIT_SECONDS)
    cls = "security_interstitial"
    while time.monotonic() < give_up:
        time.sleep(2.0)
        url, title, text, html = _snapshot(page)
        cls = classify_page(url, title, text, html)
        if cls != "security_interstitial":
            break
    return cls


def _advance_from_job_page(page) -> str | None:
    """Open the Indeed Apply form in this tab. Returns an external URL when the job
    only offers 'Apply on company site' (not an Indeed-hosted application)."""
    link = page.ele('css:a[href*="smartapply.indeed.com"]', timeout=3)
    if link and link.attr("href"):
        page.get(link.attr("href"), timeout=NAV_TIMEOUT)  # same tab: no popup handling needed
        time.sleep(2.0)
        return None
    external = page.ele('xpath://a[contains(., "company site")] | //button[contains(., "company site")]',
                        timeout=1)
    if external:
        return external.attr("href") or "company site"
    _click_first(page, ["apply now", "easy apply"])
    time.sleep(2.0)
    return None


# Visible, enabled buttons only: Indeed keeps hidden "Apply now"/"Submit" templates in the DOM.
_BUTTONS_JS = """return [...document.querySelectorAll('button,[role=button],input[type=submit]')]
  .filter(e => e.offsetParent !== null && !e.disabled)
  .map((e, i) => { e.setAttribute('data-hermes-btn', String(i));
    return [String(i), (e.innerText || e.value || '').trim().toLowerCase().replace(/\\s+/g, ' '),
            e.getAttribute('data-testid') || '']; })"""
# Diagnostics for FORM_CHANGED: every button incl. hidden/disabled, so a layout change is visible in the DB.
_ALL_BUTTONS_JS = """return [...document.querySelectorAll('button,[role=button],input[type=submit]')]
  .map(e => (e.innerText || e.value || '').trim().slice(0, 30) + (e.disabled ? '[disabled]' : '')
            + (e.offsetParent === null ? '[hidden]' : '')).filter(Boolean).slice(-12)"""
_FINAL_BTN_RE = re.compile(r"^(submit( your)? application|submit|apply)$")
_NEXT_BTN_RE = re.compile(r"^(continue|next|review( your application)?|continue to next step)$")


def _pick_button(buttons: list) -> tuple[str | None, bool]:
    """(data-hermes-btn index, is_final_submit) — pure, unit-tested."""
    for idx, text, testid in buttons:
        if _FINAL_BTN_RE.match(text) or "submit" in testid.lower():
            return idx, True
    for idx, text, testid in buttons:
        if _NEXT_BTN_RE.match(text) or "continue-button" in testid:
            return idx, False
    return None, False


def _click_next_or_submit(page, dry_run: bool) -> tuple[bool, bool]:
    """Returns (advanced, was_final_submit). Never clicks the final submit in dry_run."""
    idx, is_final = None, False
    for _ in range(6):  # Indeed disables Continue/Submit for a few seconds while a step validates
        try:
            idx, is_final = _pick_button(page.run_js(_BUTTONS_JS) or [])
        except Exception as exc:  # page navigated mid-script; rescan
            print(f"  [indeed] button scan failed: {exc}")
        if idx is not None:
            break
        time.sleep(2)
    if idx is None:
        return False, False
    if is_final and dry_run:
        return False, True
    try:
        page.ele(f'css:[data-hermes-btn="{idx}"]', timeout=2).click(by_js=None)
    except Exception as exc:  # click intercepted/detached → treated as "no control"
        print(f"  [indeed] click failed: {exc}")
        return False, False
    time.sleep(2.5)
    return True, is_final


def _drive_application(page, job: dict, cover_letter: str, resume_path: str,
                        screenshot_path: str, dry_run: bool, deadline: float) -> ApplyResult:
    for _ in range(MAX_FORM_STEPS):
        if time.monotonic() > deadline:
            return ApplyResult(states.FAILED, detail="exceeded 6-minute apply budget",
                                screenshot=_screenshot(page, screenshot_path))

        url, title, text, html = _snapshot(page)
        cls = classify_page(url, title, text, html)

        if cls == "security_interstitial":
            cls = _wait_out_interstitial(page, deadline)
            if cls == "security_interstitial":
                return ApplyResult(states.SECURITY_INTERSTITIAL, detail="Cloudflare check did not clear",
                                    screenshot=_screenshot(page, screenshot_path))

        result = _handle_classified_page(page, cls, job, cover_letter, resume_path,
                                          screenshot_path, dry_run, url, title, text, html)
        if result is not None:
            return result
        # cls in {"job_page", "application"} with no terminal result yet: loop continues

    # Nothing was submitted unless a final click happened (handled above), so this is
    # a form we could not drive — never "unconfirmed submission".
    return ApplyResult(states.FORM_CHANGED, detail="ran out of form steps",
                        screenshot=_screenshot(page, screenshot_path))


def _handle_classified_page(page, cls: str, job: dict, cover_letter: str, resume_path: str,
                             screenshot_path: str, dry_run: bool,
                             url: str, title: str, text: str, html: str) -> ApplyResult | None:
    """Returns a terminal ApplyResult, or None to keep driving the loop."""
    hay = f"{title}\n{text}\n{html}"

    if cls == "login":
        return ApplyResult(states.LOGIN_REQUIRED, detail="Indeed session expired",
                            screenshot=_screenshot(page, screenshot_path))
    if cls == "captcha":
        return ApplyResult(states.CAPTCHA_REQUIRED, detail="hCaptcha/reCAPTCHA challenge shown",
                            screenshot=_screenshot(page, screenshot_path))
    if cls == "otp":
        detail = _handle_otp(page, hay)
        if detail:
            return ApplyResult(states.OTP_REQUIRED, detail=detail,
                                screenshot=_screenshot(page, screenshot_path))
        return None  # code accepted — re-classify next loop iteration
    if cls == "success":
        return ApplyResult(states.SUBMITTED, evidence=_success_evidence(hay, url))
    if cls == "already_applied":
        return ApplyResult(states.ALREADY_APPLIED, detail="Indeed reports this job was already applied to")
    if cls == "expired":
        return ApplyResult(states.EXPIRED, detail="posting has expired or is no longer available")
    if cls == "job_page":
        external = _advance_from_job_page(page)
        if external:
            return ApplyResult(states.UNSUPPORTED_CHANNEL, detail=f"external apply: {external[:200]}")
        return None
    if cls == "application":
        detail = _fill_form_step(page, cover_letter, resume_path)
        if detail:
            return ApplyResult(states.FORM_CHANGED, detail=detail,
                                screenshot=_screenshot(page, screenshot_path))
        advanced, was_final = _click_next_or_submit(page, dry_run)
        if was_final and dry_run:
            return ApplyResult(states.DRY_RUN_OK, detail="stopped before clicking final submit")
        if was_final and advanced:
            time.sleep(1.5)
            url2, title2, text2, html2 = _snapshot(page)
            cls2 = classify_page(url2, title2, text2, html2)
            if cls2 == "success":
                return ApplyResult(states.SUBMITTED, evidence=_success_evidence(f"{title2}\n{text2}\n{html2}", url2))
            return ApplyResult(states.SUBMISSION_UNCONFIRMED,
                                detail="clicked submit but no success signal followed",
                                screenshot=_screenshot(page, screenshot_path))
        if not advanced:
            try:
                seen = page.run_js(_ALL_BUTTONS_JS)
            except Exception as exc:  # diagnostics only
                seen = f"<scan failed: {exc}>"
            if os.environ.get("HERMES_DEBUG_DUMP"):
                Path(os.environ["HERMES_DEBUG_DUMP"]).write_text(text + "\n\n" + html)
            return ApplyResult(states.FORM_CHANGED, detail=f"no Continue/Next/Submit control found; buttons={seen}",
                                screenshot=_screenshot(page, screenshot_path))
        return None
    return ApplyResult(states.FAILED, detail=f"unrecognized page state (url={url})",
                        screenshot=_screenshot(page, screenshot_path))


def _close_browser(page) -> None:
    if not page:
        return
    try:
        page.quit()
    except Exception:
        pass


def run_indeed_apply(job: dict, cover_letter: str, resume_path: str,
                      screenshot_path: str, dry_run: bool = False) -> ApplyResult:
    """Apply to one Indeed job. Always closes the browser it opened."""
    ensure_virtual_display()

    page = None
    try:
        try:
            page = _launch_browser()
        except Exception as exc:
            return ApplyResult(states.NETWORK_ERROR, detail=f"browser launch failed: {exc}"[:300])

        _seed_session_cookies(page)

        try:
            page.get(job["url"], timeout=NAV_TIMEOUT)
        except Exception as exc:
            return ApplyResult(states.NETWORK_ERROR, detail=f"navigation failed: {exc}"[:300],
                                screenshot=_screenshot(page, screenshot_path))

        time.sleep(2.0)
        deadline = time.monotonic() + MAX_APPLY_SECONDS
        return _drive_application(page, job, cover_letter, resume_path, screenshot_path, dry_run, deadline)

    except Exception as exc:
        return ApplyResult(states.FAILED, detail=f"unexpected: {exc}"[:300],
                            screenshot=_screenshot(page, screenshot_path))
    finally:
        _close_browser(page)
