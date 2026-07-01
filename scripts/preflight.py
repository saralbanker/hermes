#!/usr/bin/env python3
"""
preflight.py — Run before the pipeline to catch failures early.

Test 1: Ollama — can it respond with real inference (not just ping)?
Test 2: DrissionPage — can it load indeed.com with saved session?

Exit 0 = all pass. Exit 1 = something failed (prints what).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

COOKIES_PATH = ROOT / "output" / "indeed_session.json"
PASS = "  ✓"
FAIL = "  ✗"


def test_ollama() -> bool:
    import requests

    print("\n[preflight] Test 1 — Ollama inference (qwen3:4b scoring a fake job)...")

    prompt = (
        "Rate this job for a Full Stack Engineer with 2 years of experience in TypeScript and React. "
        "Job: Senior React Developer at a fintech startup, remote, TypeScript required. "
        "Reply with ONLY a JSON object: {\"score\": <0-10>, \"reason\": \"<one sentence>\"}. "
        "No other text."
    )
    # Warm-up: load the model into RAM before the real test (cold start = 60-120s on CPU)
    try:
        requests.post(
            "http://localhost:11434/api/chat",
            json={"model": "qwen3:4b", "messages": [{"role": "user", "content": "hi"}],
                  "stream": False, "options": {"num_predict": 1}, "keep_alive": "15m"},
            timeout=240,
        )
    except Exception:
        pass  # ignore warmup errors — real test below catches failures

    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen3:4b",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1},
                "keep_alive": "15m",
            },
            timeout=240,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"].strip()
        # Sanity check: contains a score-like structure
        if '"score"' in content or "score" in content.lower():
            print(f"{PASS} Ollama responded in {resp.elapsed.total_seconds():.1f}s")
            print(f"     Response preview: {content[:120]}")
            return True
        else:
            print(f"{FAIL} Ollama response missing score field")
            print(f"     Got: {content[:200]}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"{FAIL} Ollama not reachable — is it running? (ollama serve)")
        return False
    except requests.exceptions.Timeout:
        print(f"{FAIL} Ollama timed out after 180s — model may not be loaded")
        return False
    except Exception as e:
        print(f"{FAIL} Ollama error: {e}")
        return False


def test_indeed_session() -> bool:
    print("\n[preflight] Test 2 — DrissionPage + Indeed session...")

    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        print(f"{FAIL} DrissionPage not installed — run: pip install DrissionPage")
        return False

    if not COOKIES_PATH.exists():
        print(f"{FAIL} No Indeed session found at {COOKIES_PATH}")
        print("     Run: python scripts/indeed_setup.py")
        return False

    co = ChromiumOptions()
    co.headless(True)
    co.set_argument("--no-sandbox")
    co.set_argument("--disable-dev-shm-usage")
    co.set_argument("--disable-blink-features=AutomationControlled")

    page = None
    try:
        page = ChromiumPage(addr_or_opts=co)
        page.set.timeouts(base=15, page_load=30, script=15)

        # Load cookies
        page.get("https://in.indeed.com")
        time.sleep(2)
        try:
            cookies = json.loads(COOKIES_PATH.read_text())
            for ck in cookies:
                try:
                    page.set.cookies(ck)
                except Exception:
                    pass
        except Exception as e:
            print(f"{FAIL} Could not load cookies: {e}")
            return False

        # Navigate to Indeed and check login state
        page.get("https://in.indeed.com")
        time.sleep(3)
        html_lower = page.html.lower()

        login_indicators = ["sign in", "log in", "create an account"]
        logged_in_indicators = ["my jobs", "my account", "profile", "resume", "notifications"]

        if any(kw in html_lower for kw in logged_in_indicators):
            print(f"{PASS} Indeed session active — logged in")
            return True
        elif any(kw in html_lower for kw in login_indicators):
            print(f"{FAIL} Indeed session expired — re-run: python scripts/indeed_setup.py")
            return False
        else:
            # Page loaded but can't determine state — check title at least
            title = page.title or ""
            if "indeed" in title.lower():
                print(f"{PASS} Indeed loaded (session state unclear, proceeding)")
                return True
            print(f"{FAIL} Could not verify Indeed session (title: {title[:60]})")
            return False

    except Exception as e:
        print(f"{FAIL} DrissionPage error: {e}")
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
            print("  BLOCKED: Ollama is not working correctly")
        if not t2:
            print("  BLOCKED: Indeed session not ready")
        print("─" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
