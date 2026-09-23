"""
ats_apply.py — Submit applications on Greenhouse, Lever and Ashby hosted forms.

    run_ats_apply(job, cover_letter, resume_path, screenshot_path, dry_run=False) -> dict
    returns {"success": bool, "error": str | None, "screenshot": str | None}

How it works:
  1. Open the ATS-hosted application form in headless Google Chrome (Playwright,
     persistent profile so cookies/trust signals accumulate across runs).
  2. Extract every form control with its visible question label, required flag and
     options (one JS pass; each control gets a data-hermes-idx for stable selection).
  3. Answer each control: resume/cover-letter/location handled here, everything else
     via answers.answer_question (truthful rules + fact-grounded LLM).
  4. A required question with no truthful answer aborts the application
     (error "unanswerable:<label>") — we never guess.
  5. Submit and classify: success text/URL, captcha challenge, validation errors.

Error codes: captcha_blocked, posting_closed, unanswerable:<label>,
form_not_submitted, unsupported_ats, browser_error:<detail>.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import requests
import yaml

from answers import answer_question

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
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=True,
        viewport={"width": 1366, "height": 900},
        user_agent=USER_AGENT,
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        args=["--disable-blink-features=AutomationControlled"],
    )


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
        return "resume" if ("resume" in label or "cv" in label or "resume" in key) else "skip"
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
            or re.search(r"current location|which city|where are you (based|located)", label):
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


def _fill_text(page, field: dict, value: str) -> None:
    loc = page.locator(_sel(field["idx"]))
    loc.fill(value)
    if field.get("combobox") or _classify(field) == "location":  # autocomplete / react-select: choose the first suggestion
        page.wait_for_timeout(1200)
        # :visible matters — intl-tel-input keeps hundreds of hidden role=option nodes.
        option = page.locator('[role="option"]:visible, .dropdown-results > div:visible, '
                              '.pac-item:visible').first
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
        if re.search(r"hcaptcha.*(challenge|frame=challenge)|recaptcha/.*/bframe", frame.url):
            try:
                el = frame.frame_element()
                box = el.bounding_box()
                if box and box["width"] > 100 and box["height"] > 100 and el.is_visible():
                    return True
            except Exception:  # detached frame — not a visible challenge
                continue
    return False


def _submit(page) -> str | None:
    """Click submit, wait, classify. Returns None on success or an error code."""
    button = page.locator(
        'button[type="submit"]:has-text("Submit"), button:has-text("Submit application"), '
        '#btn-submit, button:has-text("Submit Application")'
    ).last
    if not button.count():
        return "form_not_submitted"
    start_url = page.url
    button.click()
    for _ in range(20):  # up to ~20 s for confirmation
        page.wait_for_timeout(1000)
        body = page.inner_text("body")[:5000]
        if SUCCESS_TEXT.search(body) or re.search(r"confirmation|thank|success", page.url, re.I) \
                and page.url != start_url:
            return None
        if _captcha_challenge_visible(page):
            return "captcha_blocked"
    return "form_not_submitted"


def _open_form(page, meta: dict) -> str | None:
    page.goto(meta["apply_url"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)
    body = page.inner_text("body")[:4000]
    if CLOSED_TEXT.search(body):
        return "posting_closed"
    if not page.locator("input[type=file], input[type=email], input[name=email], #email").count():
        return "posting_closed"
    return None


def run_ats_apply(job: dict, cover_letter: str, resume_path: str, screenshot_path: str,
                  dry_run: bool = False) -> dict:
    meta = json.loads(job.get("ats_meta") or "{}")
    if meta.get("ats") not in ("greenhouse", "lever", "ashby") or not meta.get("apply_url"):
        return {"success": False, "error": "unsupported_ats", "screenshot": None}
    from playwright.sync_api import sync_playwright

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
    except Exception as exc:  # Playwright/Chrome crash: report it, pipeline continues
        return {"success": False, "error": f"browser_error:{str(exc)[:200]}", "screenshot": None}
    finally:
        Path(cover_path).unlink(missing_ok=True)
        cover_dir.rmdir()


def _apply_in_browser(ctx, meta: dict, cover_letter: str, resume_path: str, cover_path: str,
                      screenshot_path: str, dry_run: bool) -> dict:
    page = ctx.new_page()
    error = _open_form(page, meta)
    if error:
        return {"success": False, "error": error, "screenshot": _screenshot(page, screenshot_path)}
    fields = _extract_fields(page)
    if meta["ats"] == "greenhouse":
        _merge_greenhouse(fields, _greenhouse_schema(meta))
    error = _fill_all(page, fields, cover_letter, resume_path, cover_path)
    if not error:
        page.wait_for_timeout(1000)
        # Resume parsing can add fields or clear values — re-check required ones once.
        refreshed = [f for f in _extract_fields(page) if f["required"] and not f.get("prefilled")]
        if meta["ats"] == "greenhouse":
            _merge_greenhouse(refreshed, _greenhouse_schema(meta))
        error = _fill_all(page, refreshed, cover_letter, resume_path, cover_path)
    if error:
        return {"success": False, "error": error, "screenshot": _screenshot(page, screenshot_path)}
    if dry_run:
        shot = _screenshot(page, screenshot_path)
        return {"success": True, "error": None, "screenshot": shot, "note": "dry_run"}
    error = _submit(page)
    return {"success": error is None, "error": error, "screenshot": _screenshot(page, screenshot_path)}
