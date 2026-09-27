"""
ats_apply.py — Submit applications on Greenhouse, Lever and Ashby hosted forms.

    run_ats_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False)
        -> states.ApplyResult

How it works:
  1. Open the ATS-hosted application form in headful Google Chrome inside a private
     Xvfb display (display.ensure_virtual_display()), via Playwright with a
     persistent profile so cookies/trust signals accumulate across runs.
  2. Extract every form control with its visible question label, required flag and
     options (one JS pass; each control gets a data-hermes-idx for stable selection).
  3. Answer each control: resume/cover-letter/location handled here, everything else
     via answers.answer_question (truthful rules + fact-grounded LLM).
  4. A required question with no truthful answer aborts the application
     (FORM_CHANGED with the question label) — we never guess.
  5. dry_run fills every field and returns DRY_RUN_OK without clicking submit.
     Otherwise: submit and classify success text/URL, captcha challenge, or
     validation errors, into the matching states.ApplyResult.

Internal error codes (mapped to ApplyResult states by _result_for_error):
  captcha_blocked, blocked_antibot:<signal>, otp_required:<prompt>, posting_closed,
  form_missing_fields, unanswerable:<label>, validation_error:<text>, form_not_submitted,
  unconfirmed, unsupported_ats, network_error:<detail>, browser_error:<detail>.
"""
from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path

import requests
import yaml

import otp_resolver
import states
from answers import answer_question
from display import ensure_virtual_display

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover — pure functions (used by tests) must import fine either way
    sync_playwright = None
    PWTimeoutError = PWError = Exception

ROOT = Path(__file__).parent.parent
PROFILE_DIR = ROOT / "output" / "chrome-ats-profile"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/142.0.0.0 Safari/537.36"
)
HOME_LOCATION = "Ahmedabad"
CURRENT_COMPANY = "Freelance (self-employed)"

SUCCESS_TEXT = re.compile(
    r"thank(s| you) for (applying|your (application|interest))|application (has been )?"
    r"(submitted|received)|we('ve| have) received your application|successfully (submitted|applied)",
    re.IGNORECASE,
)
CLOSED_TEXT = re.compile(
    r"no longer (accepting|available|open)|job (is )?(closed|not found)|position (has been )?filled|"
    r"page (you|you're) looking for|couldn't find (that|this) job",
    re.IGNORECASE,
)
VALIDATION_ERROR_TEXT = re.compile(
    r"is required\b|please (enter|select|complete|fill|provide|choose)|this field is required|"
    r"(?<!indicates a )(?<!indicates an )required field|invalid (email|phone|url|format)|"
    r"field is missing",
    re.IGNORECASE,
)
# A Greenhouse email-verification gate — observed live on Cloudflare's own board: after a
# fully-valid submit, Greenhouse held the application and showed "A verification code was
# sent to <email>... enter the ... code to confirm you're a human" with a 6-8 box code input.
# This is not a visible CAPTCHA (_captcha_challenge_visible) and matches none of the other
# text patterns, so without this it silently fell through 20s of polling to a misleading
# "submission_unconfirmed" instead of the OTP-gated state it actually is.
EMAIL_OTP_TEXT = re.compile(
    r"verification code (was|has been) sent|enter the .{0,20}code to confirm|"
    r"(security|verification) code.{0,60}(sent|confirm)|sent.{0,40}(security|verification) code|"
    r"check your (email|inbox) for.{0,20}code|enter the code (we|that we) (sent|emailed)",
    re.IGNORECASE,
)
CAPTCHA_FRAME_RE = re.compile(r"hcaptcha.*(challenge|frame=challenge)|recaptcha/.*/bframe", re.IGNORECASE)
# Signals that the ATS's own backend silently rejected the submission on a bot-risk score
# (Greenhouse's invisible reCAPTCHA Enterprise, Ashby's spam flag) rather than a form or
# network error. There is no challenge to solve here — the point is to name the block
# precisely instead of recording a generic failure, never to defeat it.
ANTIBOT_RESPONSE_RE = re.compile(
    r"recaptcha|hcaptcha|h-captcha|turnstile|arkose|funcaptcha|marked as .{0,20}spam|"
    r"flagged as .{0,20}spam|spam.?filter|bot.?(detect|check)|"
    r"automated (traffic|request|submission)|suspicious activity|risk.?score|"
    r"verification failed|security check failed|couldn.t submit your application",
    re.IGNORECASE,
)
DECLINE_OPTION = re.compile(r"decline|prefer not|don.t wish|do not wish|not to (say|disclose)", re.I)
EEO_LABEL = re.compile(r"\bgender|\brace\b|ethnic|veteran|disabilit|hispanic|sexual orientation|\bpronouns?\b", re.I)
# Questions asking the candidate to certify a no-AI application. Hermes writes cover letters
# with a local LLM, so affirming these would be a lie: leave them unanswered (a required one
# aborts the application).
AI_POLICY_LABEL = re.compile(
    r"ai policy|without (the )?(use of |using )?(ai|artificial intelligence)|not (use|used) (ai|any ai)|"
    r"ai[- ]generated|(certify|confirm).{0,40}(ai|chatgpt|llm)", re.I)

MOTIVATION_LABEL = re.compile(
    r"why (do you want|are you (interested|applying|excited)|this (role|company|position)|us\b|join)|"
    r"^why [\w .&-]{2,40}\?|what (excites|interests|attracts) you|motivat", re.I)
EDU_END_LABEL = re.compile(r"end date year|graduation year|year of graduation", re.I)
EDU_START_LABEL = re.compile(r"start date year", re.I)
DEGREE_LABEL = re.compile(r"^degree\b", re.I)


def _education() -> dict:
    """Education years from config.yaml profile (education_start_year / education_end_year)."""
    profile = yaml.safe_load(open(ROOT / "config.yaml")).get("profile", {})
    return {"start": profile.get("education_start_year"), "end": profile.get("education_end_year", 2026)}


# Serialises every visible form control into a descriptor list (see _extract_fields).
EXTRACT_JS = (ROOT / "src" / "ats_extract.js").read_text()


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

def _launch(pw):
    from display import cleanup_orphan_browsers

    ensure_virtual_display()  # headful Chrome inside a private Xvfb display — see display.py
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
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
    except Exception:
        cleanup_orphan_browsers()
        raise


def _screenshot(page, path: str) -> str | None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=path, full_page=True)
        return path
    except Exception as exc:  # screenshot is diagnostic only — never fail the apply on it
        print(f"  [ats] screenshot failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _extract_fields(page) -> list[dict]:
    """[{idx, tag, type, label, required, options:[{text, idx}], name, id}] for visible controls."""
    return page.evaluate(EXTRACT_JS)


def _greenhouse_schema(meta: dict) -> dict[str, dict]:
    """Greenhouse question schema keyed by field name (type, required, option labels)."""
    url = (f"https://boards-api.greenhouse.io/v1/boards/{meta['token']}/jobs/"
           f"{meta['job_id']}?questions=true")
    try:
        data = requests.get(url, timeout=20).json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  [ats] greenhouse schema fetch failed: {exc}")
        return {}
    schema = {}
    for q in data.get("questions", []):
        for f in q.get("fields", []):
            schema[f["name"]] = {
                "label": q.get("label", ""),
                "required": bool(q.get("required")),
                "type": f.get("type", ""),
                "options": [v.get("label", "") for v in f.get("values", [])],
            }
    return schema


# ---------------------------------------------------------------------------
# Answer selection
# ---------------------------------------------------------------------------

def _clean_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.replace("✱", "").replace("*", "")).strip()


def _classify(field: dict) -> str:
    """resume | cover_file | cover_text | location | company | eeo | generic."""
    label = field["label"].lower()
    key = f"{field.get('name', '')} {field.get('id', '')}".lower()
    if field["type"] == "file":
        if "cover" in label or "cover" in key:
            return "cover_file"
        if "resume" in label or "cv" in label or "resume" in key:
            return "resume"
        if not label.strip():
            # An UNLABELED file input — verified live on a real Workable form
            # (apply.workable.com/runware): its required Resume field extracts with an
            # empty label and an opaque id ("input_files_input_<random>"), so none of the
            # checks above can match it. Classifying it "skip" let the whole attachment go
            # silently unfilled — dry-run reported success, and the real submission then
            # failed on the site's own "Please select a file" validation. A file input
            # with NO label at all is, in practice, essentially always the resume — but a
            # field with a real label the checks above didn't recognize (e.g. "Portfolio
            # (optional)") must stay "skip": we do not guess what a named field is for.
            return "resume"
        return "skip"
    if re.search(r"cover letter|additional information|anything else|comments", label) \
            or key.strip() == "comments":
        return "cover_text" if field["tag"] == "TEXTAREA" else "generic"
    if field["tag"] == "TEXTAREA" and MOTIVATION_LABEL.search(_clean_label(field["label"])):
        return "cover_text"  # tailored, fact-checked letter answers "why us?" honestly
    if DEGREE_LABEL.search(label) and field.get("combobox") and not field["options"]:
        return "degree"
    if EDU_END_LABEL.search(label) or EDU_START_LABEL.search(label):
        return "edu_year"
    if key.strip() in ("location", "location-input location") or "candidate-location" in key \
            or re.search(r"current location|which city|where are you (based|located)|"
                         r"^location\b", label):
        return "location"
    if re.search(r"current (company|employer|organi[sz]ation)", label) or key.strip() == "org":
        return "company"
    if EEO_LABEL.search(label):
        return "eeo"
    return "generic"


def _answer_for(field: dict, cover_letter: str) -> str | None:
    kind = _classify(field)
    label = _clean_label(field["label"])
    options = [o["text"] for o in field.get("options", [])]
    if kind == "cover_text":
        return cover_letter
    if kind == "location":
        return HOME_LOCATION
    if kind == "company":
        return CURRENT_COMPANY
    if kind == "degree":
        return "Diploma"
    if kind == "edu_year":
        year = _education()["end" if EDU_END_LABEL.search(label) else "start"]
        return str(year) if year else None
    if kind == "eeo":
        return next((o for o in options if DECLINE_OPTION.search(o)), None)
    if AI_POLICY_LABEL.search(label):
        return None
    if options and re.search(r"notice period|when can you (start|join)|joining", label, re.I):
        # Available immediately: the shortest bucket is the truthful choice.
        shortest = re.compile(r"immediate|less|^\s*0|15 days|1 month or less|within", re.I)
        picked = next((o for o in options if shortest.search(o)), None)
        if picked:
            return picked
    if options:
        return answer_question(label, options, kind="choice")
    if field["type"] == "checkbox":
        return answer_question(label, kind="boolean")
    return answer_question(label, kind="textarea" if field["tag"] == "TEXTAREA" else "text")


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------

def _sel(idx: int) -> str:
    return f'[data-hermes-idx="{idx}"]'


LOCATION_OPTION_SEL = '[role="option"]:visible, .dropdown-results > div:visible, .pac-item:visible'


def _fill_text(page, field: dict, value: str) -> None:
    loc = page.locator(_sel(field["idx"]))
    is_location = _classify(field) == "location"
    try:
        if is_location:
            # Google Places (".pac-item") and similar city-autocomplete widgets listen for
            # real per-keystroke events, not the single bulk value-set .fill() performs —
            # observed live on Cloudflare's Greenhouse form: .fill("Ahmedabad") left no
            # dropdown suggestion to click, and Greenhouse then cleared the "unselected"
            # text on blur/submit, so the required field silently ended up empty again.
            loc.click(timeout=5000)
            loc.press_sequentially(value, delay=80)
        else:
            loc.fill(value)
    except PWError as exc:
        # A live-DOM checkbox/radio that our extraction pass mis-typed as fillable text
        # (seen on Greenhouse's own consent control after a resume-parse re-render shifted
        # the field list) — Playwright's own error names the real control type, so recover
        # by acting on it as the checkbox it actually is rather than aborting the question.
        if "cannot be filled" not in str(exc):
            raise
        if value.lower().startswith("yes"):
            loc.check(force=True)
        return
    if field.get("combobox") or is_location:  # autocomplete / react-select: choose the first suggestion
        page.wait_for_timeout(1500)
        # :visible matters — intl-tel-input keeps hundreds of hidden role=option nodes.
        option = page.locator(LOCATION_OPTION_SEL).first
        if not option.count() and is_location:
            # One retry: a slow places-API round trip on the first keystroke can miss the
            # first wait entirely.
            page.wait_for_timeout(1500)
            option = page.locator(LOCATION_OPTION_SEL).first
        # Never press Enter here: in a <form> it submits the application.
        if option.count():
            option.click(timeout=5000)


def _fill_choice(page, field: dict, value: str) -> bool:
    """Select/radio/checkbox-group/Yes-No buttons/react-select. False if option missing."""
    match = next((o for o in field["options"] if o["text"] == value), None)
    if field["tag"] == "SELECT":
        page.locator(_sel(field["idx"])).select_option(label=value)
        return True
    if match and match.get("idx") is not None:
        page.locator(_sel(match["idx"])).click(force=True)
        return True
    if field["type"] == "checkbox" and match is not None:
        # A single checkbox whose Yes/No labels came from _merge_greenhouse (idx=None —
        # the schema names the two answers but there is only one DOM node, the checkbox
        # itself, not a react-select). This is Greenhouse's own consent/compliance
        # control (e.g. "Acknowledge/Confirm — Candidate Privacy Policy"); treating it as
        # a combobox below would call .fill() on a checkbox and fail outright.
        if not value.lower().startswith("no"):
            page.locator(_sel(field["idx"])).check(force=True)
        return True
    if field.get("combobox"):  # react-select (Greenhouse): open, type, pick exact option
        box = page.locator(_sel(field["idx"]))
        box.click(timeout=5000)
        box.fill(value)
        page.wait_for_timeout(700)
        opts = page.locator('[role="option"]:visible')
        exact = opts.filter(has_text=re.compile(rf"^\s*{re.escape(value)}\s*$"))
        target = exact.first if exact.count() else opts.first
        if target.count():
            target.click(timeout=5000)
            return True
    return False


def _fill_degree(page, field: dict) -> bool:
    """Greenhouse degree list has no 'Diploma' on most boards — accept Diploma or Other only."""
    page.locator(_sel(field["idx"])).click(timeout=5000)
    page.wait_for_timeout(800)
    options = page.locator('[role="option"]:visible')
    for pattern in (r"diploma", r"^\s*other\s*$"):
        opt = options.filter(has_text=re.compile(pattern, re.I)).first
        if opt.count():
            opt.click(timeout=5000)
            return True
    return False


def _fill_field(page, field: dict, value: str, resume_path: str, cover_path: str) -> bool:
    kind = _classify(field)
    if kind == "resume":
        page.locator(_sel(field["idx"])).set_input_files(resume_path)
        page.wait_for_timeout(2500)  # Lever/Ashby parse the resume and may autofill fields
        return True
    if kind == "cover_file":
        page.locator(_sel(field["idx"])).set_input_files(cover_path)
        return True
    if kind == "degree":
        return _fill_degree(page, field)
    if field["options"] or field.get("choice"):
        return _fill_choice(page, field, value)
    if field["type"] == "number":
        digits = re.search(r"\d+(\.\d+)?", value)
        if not digits:
            return False
        value = digits.group()
    if field["type"] == "checkbox":
        if value.lower().startswith("yes"):
            page.locator(_sel(field["idx"])).check(force=True)
        return True
    _fill_text(page, field, value)
    return True


def _merge_greenhouse(fields: list[dict], schema: dict[str, dict]) -> None:
    """Greenhouse react-selects render as text inputs: attach the API's options/required flag."""
    for f in fields:
        s = schema.get(f.get("id") or "") or schema.get(f.get("name") or "")
        if not s:
            continue
        f["required"] = f["required"] or s["required"]
        if s["options"] and not f["options"]:
            f["options"] = [{"text": o, "idx": None} for o in s["options"]]
            f["combobox"] = True
            f["choice"] = True


def _settle(page) -> None:
    """Blur the just-filled control (commits its value in React-style forms, and is what
    triggers Ashby's own client-side validation) and give any resulting network activity a
    moment to finish before moving on. Bounded: a page with persistent background polling
    would otherwise make networkidle hang for the full timeout on every single field.
    Added for the real Snowflake/Ashby race — its own "form needs corrections" banner
    listed fields as missing that our fill had already visibly set, most likely because
    submit was clicked before Ashby's debounced validation had caught up."""
    try:
        page.keyboard.press("Tab")
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=1500)
    except Exception:  # a page that never truly idles must not block filling
        pass


def _fill_all(page, fields: list[dict], cover_letter: str, resume_path: str,
              cover_path: str) -> str | None:
    """Fill every field. Returns an error code, or None when all required fields are filled."""
    for field in fields:
        if field.get("prefilled") and _classify(field) not in ("resume", "cover_file"):
            continue
        value = None if _classify(field) in ("resume", "cover_file", "skip") \
            else _answer_for(field, cover_letter)
        if _classify(field) == "skip":
            continue
        if value is None and _classify(field) not in ("resume", "cover_file"):
            if field["required"]:
                return f"unanswerable:{_clean_label(field['label'])[:80]}"
            continue
        try:
            ok = _fill_field(page, field, value or "", resume_path, cover_path)
            # Not for location/combobox controls: real regression, live on Snowflake —
            # Tab immediately after a dropdown selection interrupted the app's own debounced
            # "commit" and made a visibly-filled, previously-working Location field come
            # back as "missing" in Ashby's validation. Plain text/choice controls are fine.
            if ok and not (field.get("combobox") or _classify(field) == "location"):
                _settle(page)
        except Exception as exc:  # one widget failing must not hide which question it was
            ok = False
            print(f"  [ats] fill error on '{_clean_label(field['label'])[:60]}': {str(exc)[:120]}")
        if not ok and field["required"]:
            return f"unanswerable:{_clean_label(field['label'])[:80]}"
    return None


# ---------------------------------------------------------------------------
# Submit + outcome detection
# ---------------------------------------------------------------------------

def _captcha_challenge_visible(page) -> bool:
    for frame in page.frames:
        if CAPTCHA_FRAME_RE.search(frame.url):
            try:
                el = frame.frame_element()
                box = el.bounding_box()
                if box and box["width"] > 100 and box["height"] > 100 and el.is_visible():
                    return True
            except Exception:  # detached frame — not a visible challenge
                continue
    return False


def _new_match(pattern: re.Pattern, body: str, baseline: str):
    """The first regex match whose surrounding text is not already present in `baseline` —
    static instructional copy the page always shows (Greenhouse's "* indicates a required
    field", an Ashby helper string) must never be mistaken for a validation/OTP message the
    submit itself caused. Comparing a window around each match, not just the matched phrase
    alone, avoids the opposite mistake: suppressing a real new error that happens to reuse a
    generic word ("please enter") also used, elsewhere, on the same page — so every match is
    checked in turn, not just the first (which may be the old, benign one)."""
    for m in pattern.finditer(body):
        window = body[max(0, m.start() - 20):m.end() + 20]
        if window not in baseline:
            return m
    return None


def _watch_submit_responses(page) -> tuple[list[str], callable]:
    """Record bot-risk signals from failed XHR/fetch responses while the submit request is
    in flight. Returns (matches, stop) — stop() must be called once done watching."""
    matches: list[str] = []

    def _on_response(resp) -> None:
        try:
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            snippet = "" if resp.ok else (resp.text() or "")[:500]
            hay = f"{resp.url} {resp.status} {snippet}"
            if not resp.ok and (ANTIBOT_RESPONSE_RE.search(hay) or resp.status in (401, 403)):
                matches.append(f"{resp.status} {resp.url[:150]}: {snippet[:200]}")
        except Exception:  # a response we can't read must not break submission
            pass

    page.on("response", _on_response)
    return matches, lambda: page.remove_listener("response", _on_response)


def _submit(page) -> tuple[str | None, str | None]:
    """Click submit, wait, classify. Returns (error_code, evidence). error_code is
    None with evidence set on success."""
    button = page.locator(
        'button[type="submit"]:has-text("Submit"), button:has-text("Submit application"), '
        '#btn-submit, button:has-text("Submit Application")'
    ).last
    if not button.count():
        return "form_not_submitted", None
    _settle(page)  # commit the last-filled field's value before reading the pre-click baseline
    start_url = page.url
    # Static instructional copy present BEFORE the click ("* indicates a required field" on
    # Greenhouse, an Ashby "Please enter..." helper string) must never count as a validation
    # error or OTP prompt CAUSED by the submit — only newly-appeared text can be. Observed
    # live on both Greenhouse (Cloudflare) and Ashby (Snowflake): a fully-valid submission was
    # misclassified as a validation error purely because boilerplate on the page happened to
    # match the same generic phrase the form always shows.
    try:
        baseline_body = page.inner_text("body")
    except Exception:
        baseline_body = ""
    antibot_hits, stop_watching = _watch_submit_responses(page)
    try:
        button.click()
    except PWTimeoutError as exc:
        stop_watching()
        return f"network_error:{str(exc)[:150]}", None
    try:
        for _ in range(20):  # up to ~20 s for confirmation
            page.wait_for_timeout(1000)
            try:
                # No slice here: a long job posting (Cloudflare's runs past 20,000 chars
                # once the form itself is included) pushes an inline validation error, or
                # even the confirmation message on some boards, past a 5,000-char window —
                # observed live: a real "Please enter your location" error went undetected
                # this way and the submission was recorded as merely unconfirmed instead of
                # the form error it actually was.
                body = page.inner_text("body")
            except Exception:  # page mid-navigation — try again next tick
                body = ""
            match = SUCCESS_TEXT.search(body)
            if match:
                return None, match.group(0)
            if page.url != start_url and re.search(r"confirmation|thank|success", page.url, re.I):
                return None, page.url
            if antibot_hits:
                return f"blocked_antibot:{antibot_hits[0]}", None
            page_antibot = _new_match(ANTIBOT_RESPONSE_RE, body, baseline_body)
            if page_antibot:
                # Real Ashby/Notion outcome: "Your application submission was flagged as
                # possible spam" is a page banner, not a failed network response — Ashby's
                # GraphQL mutation still answers 200 OK, so _watch_submit_responses (which
                # only inspects non-2xx/401/403 responses) never sees it. Only the rendered
                # page says so.
                return f"blocked_antibot:{page_antibot.group(0)}", None
            if _captcha_challenge_visible(page):
                return "captcha_blocked", None
            otp = _new_match(EMAIL_OTP_TEXT, body, baseline_body)
            if otp:
                return f"otp_required:{otp.group(0)}", None
            err = _new_match(VALIDATION_ERROR_TEXT, body, baseline_body)
            if err:
                return f"validation_error:{err.group(0)}", None
        if antibot_hits:  # a late/slow response can land after the last body check above
            return f"blocked_antibot:{antibot_hits[0]}", None
        return "unconfirmed", None
    finally:
        stop_watching()


def _open_form(page, meta: dict) -> str | None:
    try:
        response = page.goto(meta["apply_url"], wait_until="domcontentloaded", timeout=45000)
    except PWTimeoutError as exc:
        return f"network_error:{str(exc)[:150]}"
    if response is not None and response.status in (404, 410):
        return "posting_closed"
    page.wait_for_timeout(3500)
    if _captcha_challenge_visible(page):
        return "captcha_blocked"
    body = page.inner_text("body")[:4000]
    if CLOSED_TEXT.search(body):
        return "posting_closed"
    if not page.locator("input[type=file], input[type=email], input[name=email], #email").count():
        return "form_missing_fields"
    return None


# ---------------------------------------------------------------------------
# Error code -> ApplyResult
# ---------------------------------------------------------------------------

def _result_for_error(code: str, screenshot: str | None) -> states.ApplyResult:
    if code == "posting_closed":
        return states.ApplyResult(state=states.EXPIRED, detail="posting closed or not found",
                                  screenshot=screenshot)
    if code == "captcha_blocked":
        return states.ApplyResult(state=states.CAPTCHA_REQUIRED, detail="captcha challenge visible",
                                  screenshot=screenshot)
    if code.startswith("blocked_antibot:"):
        return states.ApplyResult(state=states.BLOCKED_ANTIBOT,
                                  detail=f"bot-risk check rejected the submission: {code.split(':', 1)[1]}",
                                  screenshot=screenshot)
    if code.startswith("otp_required:"):
        return states.ApplyResult(state=states.OTP_REQUIRED,
                                  detail=f"email verification code required: {code.split(':', 1)[1]}",
                                  screenshot=screenshot)
    if code == "form_missing_fields":
        return states.ApplyResult(state=states.FORM_CHANGED,
                                  detail="application form structure not recognized",
                                  screenshot=screenshot)
    if code.startswith("unanswerable:"):
        label = code.split(":", 1)[1]
        return states.ApplyResult(state=states.FORM_CHANGED,
                                  detail=f"no truthful answer for required question: {label}",
                                  screenshot=screenshot)
    if code.startswith("validation_error:"):
        return states.ApplyResult(state=states.FORM_CHANGED,
                                  detail=f"validation error after submit: {code.split(':', 1)[1]}",
                                  screenshot=screenshot)
    if code == "form_not_submitted":
        return states.ApplyResult(state=states.FAILED, detail="submit button not found",
                                  screenshot=screenshot)
    if code == "unconfirmed":
        return states.ApplyResult(state=states.SUBMISSION_UNCONFIRMED,
                                  detail="submit clicked, no confirmation or error detected",
                                  screenshot=screenshot)
    if code == "unsupported_ats":
        return states.ApplyResult(state=states.FAILED,
                                  detail="unsupported ats or apply_url missing from ats_meta",
                                  screenshot=screenshot)
    if code.startswith("network_error:"):
        return states.ApplyResult(state=states.NETWORK_ERROR, detail=code, screenshot=screenshot)
    return states.ApplyResult(state=states.FAILED, detail=code, screenshot=screenshot)


def run_ats_apply(job: dict, cover_letter: str, resume_path: str, screenshot_path: str,
                  dry_run: bool = False) -> states.ApplyResult:
    meta = json.loads(job.get("ats_meta") or "{}")
    if meta.get("ats") not in states.ATS_CHANNELS or not meta.get("apply_url"):
        return _result_for_error("unsupported_ats", None)

    # Recruiters see the uploaded filename, so give it a clean, human one.
    cover_dir = Path(tempfile.mkdtemp(prefix="hermes-cover-"))
    cover_path = str(cover_dir / "Saral_Banker_Cover_Letter.txt")
    Path(cover_path).write_text(cover_letter or "", encoding="utf-8")
    try:
        with sync_playwright() as pw:
            ctx = _launch(pw)
            try:
                return _apply_in_browser(ctx, meta, cover_letter, resume_path, cover_path,
                                         screenshot_path, dry_run)
            finally:
                ctx.close()
    except PWTimeoutError as exc:
        return states.ApplyResult(state=states.NETWORK_ERROR, detail=f"timeout: {str(exc)[:200]}")
    except PWError as exc:
        msg = str(exc)
        if re.search(r"net::ERR_|timeout|ECONNRESET|ENOTFOUND|dns", msg, re.IGNORECASE):
            return states.ApplyResult(state=states.NETWORK_ERROR, detail=msg[:200])
        return states.ApplyResult(state=states.FAILED, detail=f"browser_error:{msg[:200]}")
    except Exception as exc:  # Playwright/Chrome crash: report it, pipeline continues
        return states.ApplyResult(state=states.FAILED, detail=f"browser_error:{str(exc)[:200]}")
    finally:
        Path(cover_path).unlink(missing_ok=True)
        cover_dir.rmdir()


def _refill_missing_required(page, meta: dict, cover_letter: str, resume_path: str,
                             cover_path: str) -> str | None:
    """Re-extract and fill any required field a fresh read shows as not-yet-prefilled.
    Called more than once: resume-parse autofill on some Ashby boards can silently clear a
    field we already filled correctly — observed live on Snowflake, where "Email" and several
    Yes/No questions we had answered came back missing at actual submit time even though a
    check 1 second earlier saw them as filled. One re-check is not always enough."""
    refreshed = [f for f in _extract_fields(page) if f["required"] and not f.get("prefilled")]
    if meta["ats"] == "greenhouse":
        _merge_greenhouse(refreshed, _greenhouse_schema(meta))
    return _fill_all(page, refreshed, cover_letter, resume_path, cover_path)


def _apply_in_browser(ctx, meta: dict, cover_letter: str, resume_path: str, cover_path: str,
                      screenshot_path: str, dry_run: bool) -> states.ApplyResult:
    page = ctx.new_page()
    error = _open_form(page, meta)
    if error:
        return _result_for_error(error, _screenshot(page, screenshot_path))
    fields = _extract_fields(page)
    if meta["ats"] == "greenhouse":
        _merge_greenhouse(fields, _greenhouse_schema(meta))
    error = _fill_all(page, fields, cover_letter, resume_path, cover_path)
    for _ in range(2):  # a slow resume-parse autofill can revert a field between checks
        if error:
            break
        page.wait_for_timeout(1200)
        error = _refill_missing_required(page, meta, cover_letter, resume_path, cover_path)
    if error:
        return _result_for_error(error, _screenshot(page, screenshot_path))
    if dry_run:
        shot = _screenshot(page, screenshot_path)
        return states.ApplyResult(state=states.DRY_RUN_OK,
                                  detail="all fields filled, submit deliberately skipped",
                                  screenshot=shot)
    submit_ts = time.time()
    error, evidence = _submit(page)
    if error and error.startswith("otp_required:") and meta["ats"] == "greenhouse":
        error, evidence = _resolve_greenhouse_otp(page, submit_ts)
    if error:
        return _result_for_error(error, _screenshot(page, screenshot_path))
    return states.ApplyResult(state=states.SUBMITTED, detail="application submitted",
                              screenshot=_screenshot(page, screenshot_path),
                              evidence=evidence or page.url)


def _resolve_greenhouse_otp(page, since_ts: float) -> tuple[str | None, str | None]:
    """Poll Gmail for the security code Greenhouse just emailed, enter it into the
    per-character boxes, and click Submit again. Never bypasses the check — just answers
    it with the code the ATS itself sent to the owner's own inbox. Falls back to
    otp_required (unchanged, retryable) if Gmail isn't configured or the code doesn't
    arrive in time; a future run tries again."""
    if not otp_resolver.is_configured():
        return "otp_required:GMAIL_APP_PASSWORD not configured", None
    code = otp_resolver.fetch_otp(timeout=180, platform="greenhouse", since_ts=since_ts - 15)
    if not code:
        return "otp_required:no verification code arrived within 180s", None
    boxes = page.locator('input[id^="security-input-"]')
    n = boxes.count()
    if n == 0 or len(code) < n:
        return f"otp_required:code box mismatch ({len(code)}-char code, {n} boxes)", None
    for i in range(n):
        boxes.nth(i).fill(code[i])
    return _submit(page)
