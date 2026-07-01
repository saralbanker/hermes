#!/usr/bin/env python3
"""
preflight.py — Fast pre-flight checks before the pipeline starts.

Test 1: Ollama — is it reachable and are both models present?
Test 2: Indeed session — does the saved session file load on indeed.com?

Deliberately lightweight: no full inference in preflight. The pipeline's own
score/tailor/apply stages handle inference failures with clear error messages.
Adding a 200s inference test here just delays every run for no gain.

Exit 0 = all pass. Exit 1 = something failed (prints what).
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

COOKIES_PATH = ROOT / "output" / "indeed_session.json"
PASS = "  ✓"
FAIL = "  ✗"
WARN = "  ⚠"

REQUIRED_MODELS = ["qwen3:4b", "qwen2.5:3b"]


def test_ollama() -> bool:
    print("\n[preflight] Test 1 — Ollama: reachable + models present...")

    # Step 1: API reachable
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=10)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"{FAIL} Ollama not reachable at localhost:11434")
        print("       Start it with: ollama serve")
        return False
    except requests.exceptions.Timeout:
        print(f"{FAIL} Ollama API timed out (is it starting up?)")
        return False
    except Exception as e:
        print(f"{FAIL} Ollama API error: {e}")
        return False

    # Step 2: required models present
    try:
        available = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        available = []

    all_present = True
    for model in REQUIRED_MODELS:
        # Match on base name (e.g. "qwen3:4b" matches "qwen3:4b")
        found = any(m == model or m.startswith(model.split(":")[0] + ":") and model in m
                    for m in available)
        if found:
            print(f"{PASS} {model} present")
        else:
            print(f"{FAIL} {model} not found — run: ollama pull {model}")
            all_present = False

    # Step 3: quick load check — call qwen2.5:3b (no thinking, responds in <5s when warm)
    if all_present:
        try:
            r = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen2.5:3b",
                    "messages": [{"role": "user", "content": "reply with just: OK"}],
                    "stream": False,
                    "options": {"num_predict": 5, "temperature": 0},
                    "keep_alive": "15m",
                },
                timeout=120,
            )
            r.raise_for_status()
            content = r.json()["message"]["content"].strip()
            elapsed = r.elapsed.total_seconds()
            print(f"{PASS} Ollama responds in {elapsed:.1f}s (model: qwen2.5:3b)")
            # Kick off qwen3:4b load in the background so it's warm when pipeline starts
            try:
                requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": "qwen3:4b",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": False,
                        "options": {"num_predict": 1},
                        "keep_alive": "15m",
                    },
                    timeout=1,  # fire-and-forget — don't wait
                )
            except Exception:
                pass  # expected timeout — just warming it up async
        except requests.exceptions.Timeout:
            print(f"{WARN} qwen2.5:3b load check timed out (120s) — Ollama may be under load")
            print("       Pipeline will proceed but first score may be slow")
            # Not a hard fail — Ollama is reachable and models are listed
        except Exception as e:
            print(f"{WARN} Quick load check failed: {e}")

    return all_present


def test_indeed_session() -> bool:
    print("\n[preflight] Test 2 — Indeed session...")

    if not COOKIES_PATH.exists():
        print(f"{FAIL} No session file at output/indeed_session.json")
        print("       Run: python scripts/indeed_setup.py")
        return False

    # Check file is readable and valid JSON with at least one cookie
    try:
        cookies = json.loads(COOKIES_PATH.read_text())
        if not isinstance(cookies, list) or len(cookies) == 0:
            print(f"{FAIL} Session file is empty or malformed")
            print("       Re-run: python scripts/indeed_setup.py")
            return False
        print(f"{PASS} Session file found ({len(cookies)} cookies)")
    except Exception as e:
        print(f"{FAIL} Could not read session file: {e}")
        return False

    # Check the session contains the Indeed auth cookie (IAST = Indeed Auth Session Token)
    cookie_names = {c.get("name", "") for c in cookies if isinstance(c, dict)}
    if "IAST" in cookie_names or "CTK" in cookie_names:
        print(f"{PASS} Indeed auth cookies present (IAST/CTK found)")
    else:
        print(f"{WARN} Auth cookie (IAST) not found — session may be incomplete")
        print(f"       Found cookies: {', '.join(sorted(cookie_names)[:8])}")

    # Light browser check — load indeed.com with session
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        print(f"{FAIL} DrissionPage not installed")
        return False

    co = ChromiumOptions()
    co.headless(True)
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-blink-features=AutomationControlled")

    page = None
    try:
        page = ChromiumPage(addr_or_opts=co)
        page.set.timeouts(base=10, page_load=20, script=10)

        page.get("https://in.indeed.com")
        time.sleep(1)
        for ck in cookies:
            try:
                page.set.cookies(ck)
            except Exception:
                pass

        page.get("https://in.indeed.com")
        time.sleep(3)

        html = page.html.lower()
        title = (page.title or "").lower()

        if "indeed" not in title and "indeed" not in html[:500]:
            print(f"{FAIL} Could not reach indeed.com (title: {page.title})")
            return False

        if any(kw in html for kw in ["sign in to", "log in to", "create an account to apply"]):
            print(f"{FAIL} Session expired — re-run: python scripts/indeed_setup.py")
            return False

        print(f"{PASS} indeed.com loaded — session active")
        return True

    except Exception as e:
        print(f"{FAIL} Browser check failed: {e}")
        return False
    finally:
        if page:
            try:
                page.quit()
            except Exception:
                pass


def main():
    print("═" * 50)
    print("  HERMES — Pre-flight checks")
    print("═" * 50)

    t1 = test_ollama()
    t2 = test_indeed_session()

    print()
    print("─" * 50)
    if t1 and t2:
        print("  All checks passed — starting pipeline")
        print("─" * 50)
        sys.exit(0)
    else:
        if not t1:
            print("  BLOCKED: Ollama not ready")
        if not t2:
            print("  BLOCKED: Indeed session not ready")
        print("─" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
