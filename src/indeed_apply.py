"""
indeed_apply.py — Deterministic Indeed form filler using DrissionPage (CDP-based, no WebDriver).
Zero API cost. No LLM per browser action — uses Ollama only for open-ended text fields.

DrissionPage uses Chrome DevTools Protocol directly, bypassing WebDriver detection
(Akamai / DataDome checks). Safe for 6-10 hr overnight runs.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yaml"
COOKIES_PATH = ROOT / "output" / "indeed_session.json"

SUCCESS_KEYWORDS = [
    "application sent", "successfully applied", "thank you for applying",
    "application complete", "we received your application", "application received",
    "your application has been submitted",
]
FAILURE_KEYWORDS = [
    "sign in", "log in", "create an account", "login required",
]


def _load_cfg() -> dict:
    return yaml.safe_load(open(CONFIG_PATH))


def _human_sleep(lo: float = 0.8, hi: float = 2.2):
    time.sleep(random.uniform(lo, hi))


def _human_type(ele, text: str):
    """Type text character by character with slight random delays."""
    ele.clear()
    for ch in text:
        ele.input(ch, clear=False)
        time.sleep(random.uniform(0.04, 0.12))


def _fill_field_if_empty(ele, value: str):
    """Fill a form field only if it's currently empty or has a placeholder."""
    try:
        current = ele.value or ""
        if not current.strip():
            _human_type(ele, value)
    except Exception:
        pass


def _qwen_answer(question: str, cfg: dict) -> str:
    """Call Ollama to answer an open-ended screening question. Short, direct answer."""
    ollama = cfg.get("inference", {}).get("local", cfg.get("ollama", {}))
    model = ollama.get("apply_model", "qwen2.5:3b")
    base_url = ollama.get("base_url", "http://localhost:11434")
    timeout = ollama.get("timeout", 120)

    p = cfg["profile"]
    system = (
        "You are Saral Banker applying for jobs. Answer screening questions directly and briefly. "
        "Maximum 3 sentences. No fluff. First person."
    )
    prompt = (
        f"Question: {question}\n\n"
        f"My background: {p['years_experience']} years, {p['education']}, "
        f"Full Stack + AI Engineer, immediately available, prefer remote.\n"
        "Answer:"
    )
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3},
                "keep_alive": "15m",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception:
        return cfg["screening_answers"].get("why_interested_template", "Eager to contribute.")


def _fill_form_page(page, cfg: dict, cover_letter: str, resume_path: str) -> bool:
    """
    Fill one page of the Indeed application form.
    Returns True if Submit button was found and clicked.
    """
    p = cfg["profile"]
    ans = cfg["screening_answers"]
    phone_clean = re.sub(r"[^\d]", "", p["phone"])[-10:]

    # ── Name fields ─────────────────────────────────────────────────────────
    for selector in [
        'input[name*="name"][name*="first" i]',
        'input[placeholder*="first name" i]',
        'input[id*="first" i]',
    ]:
        try:
            el = page.ele(f'css:{selector}', timeout=1)
            if el:
                _fill_field_if_empty(el, p["name"].split()[0])
                break
        except Exception:
            pass

    for selector in [
        'input[name*="name"][name*="last" i]',
        'input[placeholder*="last name" i]',
        'input[id*="last" i]',
    ]:
        try:
            el = page.ele(f'css:{selector}', timeout=1)
            if el:
                _fill_field_if_empty(el, p["name"].split()[-1])
                break
        except Exception:
            pass

    # Full name fallback
    for selector in [
        'input[name*="fullname" i]',
        'input[placeholder*="full name" i]',
        'input[id*="fullname" i]',
    ]:
        try:
            el = page.ele(f'css:{selector}', timeout=1)
            if el:
                _fill_field_if_empty(el, p["name"])
                break
        except Exception:
            pass

    # ── Email ────────────────────────────────────────────────────────────────
    for selector in ['input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]']:
        try:
            el = page.ele(f'css:{selector}', timeout=1)
            if el:
                _fill_field_if_empty(el, p["email"])
                break
        except Exception:
            pass

    # ── Phone ────────────────────────────────────────────────────────────────
    for selector in [
        'input[type="tel"]',
        'input[name*="phone" i]',
        'input[name*="mobile" i]',
        'input[id*="phone" i]',
    ]:
        try:
            el = page.ele(f'css:{selector}', timeout=1)
            if el:
                _fill_field_if_empty(el, phone_clean)
                break
        except Exception:
            pass

    # ── Cover letter / motivation ────────────────────────────────────────────
    if cover_letter:
        for selector in [
            'textarea[name*="cover" i]',
            'textarea[name*="motivation" i]',
            'textarea[name*="message" i]',
            'textarea[placeholder*="cover" i]',
            'textarea[placeholder*="tell us" i]',
            'textarea[placeholder*="why" i]',
        ]:
            try:
                el = page.ele(f'css:{selector}', timeout=1)
                if el:
                    _fill_field_if_empty(el, cover_letter[:2000])
                    break
            except Exception:
                pass

    # ── Years experience ─────────────────────────────────────────────────────
    for selector in [
        'input[name*="years" i]',
        'input[name*="experience" i]',
        'input[placeholder*="years" i]',
    ]:
        try:
            el = page.ele(f'css:{selector}', timeout=1)
            if el:
                _fill_field_if_empty(el, str(p["years_experience"]))
                break
        except Exception:
            pass

    # ── Resume upload ────────────────────────────────────────────────────────
    if resume_path and Path(resume_path).exists():
        for selector in ['input[type="file"]', 'input[accept*="pdf" i]']:
            try:
                el = page.ele(f'css:{selector}', timeout=1)
                if el:
                    el.input(resume_path)
                    _human_sleep(1.5, 3.0)
                    break
            except Exception:
                pass

    # ── Yes/No and Select fields ─────────────────────────────────────────────
    try:
        selects = page.eles('css:select', timeout=1)
        for sel in selects:
            label_text = ""
            try:
                parent = sel.parent()
                label_text = parent.text.lower() if parent else ""
            except Exception:
                pass
            try:
                if "sponsor" in label_text:
                    sel.select_option("No")
                elif "relocat" in label_text:
                    sel.select_option("No")
                elif "remote" in label_text or "work from home" in label_text:
                    sel.select_option("Yes")
                elif "currently employed" in label_text or "employed" in label_text:
                    sel.select_option("No")
            except Exception:
                pass
    except Exception:
        pass

    # ── Open-ended textarea questions ────────────────────────────────────────
    try:
        textareas = page.eles('css:textarea', timeout=1)
        for ta in textareas:
            try:
                current = ta.value or ""
                if current.strip():
                    continue  # already filled
                label_text = ""
                try:
                    parent = ta.parent()
                    label_text = parent.text[:200] if parent else ""
                except Exception:
                    pass
                if not label_text.strip():
                    continue
                # Use template for "why" questions, Qwen for others
                q = label_text.strip()
                if any(kw in q.lower() for kw in ["why", "interest", "motivation", "about yourself"]):
                    answer = ans.get("why_interested_template", "").strip()
                else:
                    answer = _qwen_answer(q, cfg)
                if answer:
                    _human_type(ta, answer[:500])
                    _human_sleep(0.5, 1.5)
            except Exception:
                pass
    except Exception:
        pass

    _human_sleep(1.0, 2.0)

    # ── Submit or Continue ───────────────────────────────────────────────────
    for text in ["Submit", "Apply", "Send application", "Continue", "Next"]:
        try:
            btn = page.ele(f'xpath://button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{text.lower()}")]', timeout=2)
            if btn:
                btn.click()
                _human_sleep(2.0, 4.0)
                return text.lower() in ("submit", "apply", "send application")
        except Exception:
            pass
    return False


def run_indeed_apply(
    job_url: str,
    cover_letter: str,
    resume_path: str,
    screenshot_path: str,
    timeout: int = 300,
) -> dict:
    """
    Apply to an Indeed job using DrissionPage (CDP-based, no WebDriver).
    Returns {"success": bool, "screenshot": str | None, "error": str | None}
    """
    cfg = _load_cfg()

    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        return {"success": False, "error": "DrissionPage not installed — run: pip install DrissionPage"}

    co = ChromiumOptions()
    co.headless(True)
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--window-size=1366,768")
    # Stealth: remove automation indicators
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_pref("credentials_enable_service", False)
    co.set_pref("profile.password_manager_enabled", False)

    page = None
    try:
        page = ChromiumPage(addr_or_opts=co)
        page.set.timeouts(base=15, page_load=30, script=15)

        # Load saved Indeed session cookies so we don't hit login wall
        if COOKIES_PATH.exists():
            page.get("https://in.indeed.com")
            _human_sleep(1.0, 2.0)
            try:
                cookies = json.loads(COOKIES_PATH.read_text())
                for ck in cookies:
                    try:
                        page.set.cookies(ck)
                    except Exception:
                        pass
            except Exception:
                pass

        page.get(job_url)
        _human_sleep(2.0, 4.0)

        # Check for login wall
        page_text = page.html.lower()
        if any(kw in page_text for kw in FAILURE_KEYWORDS):
            cookie_hint = "" if COOKIES_PATH.exists() else " — run: python scripts/indeed_setup.py"
            return {"success": False, "error": f"login_wall_detected{cookie_hint}"}

        # Click Apply button
        applied = False
        for text in ["apply now", "easy apply", "apply"]:
            try:
                btn = page.ele(
                    f'xpath://button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{text}")]',
                    timeout=3,
                )
                if btn:
                    btn.click()
                    _human_sleep(1.5, 3.0)
                    applied = True
                    break
            except Exception:
                pass

        if not applied:
            # Try link-based apply buttons
            try:
                btn = page.ele('css:.ia-IndeedApplyButton', timeout=3)
                if btn:
                    btn.click()
                    _human_sleep(1.5, 3.0)
            except Exception:
                pass

        # Fill multi-page form (up to 10 pages)
        submitted = False
        for page_num in range(10):
            _human_sleep(1.0, 2.0)
            page_text = page.html.lower()

            if any(kw in page_text for kw in SUCCESS_KEYWORDS):
                submitted = True
                break

            if any(kw in page_text for kw in FAILURE_KEYWORDS):
                break

            did_submit = _fill_form_page(page, cfg, cover_letter, resume_path)
            if did_submit:
                _human_sleep(2.0, 4.0)
                # Check confirmation
                final_text = page.html.lower()
                if any(kw in final_text for kw in SUCCESS_KEYWORDS):
                    submitted = True
                break

        # Screenshot
        try:
            Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
            page.get_screenshot(path=screenshot_path)
        except Exception:
            screenshot_path = None

        if submitted:
            return {"success": True, "screenshot": screenshot_path}
        else:
            return {"success": False, "error": "form_not_submitted", "screenshot": screenshot_path}

    except Exception as e:
        return {"success": False, "error": str(e)[:300]}
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass
