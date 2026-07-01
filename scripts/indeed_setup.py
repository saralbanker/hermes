#!/usr/bin/env python3
"""
indeed_setup.py — One-time Indeed session setup.

Opens a VISIBLE browser so you can log in to Indeed manually.
After you complete login, press Enter here and your session cookies
are saved to output/indeed_session.json for overnight use.

Usage:
  python scripts/indeed_setup.py
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
COOKIES_PATH = ROOT / "output" / "indeed_session.json"


def main():
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError:
        print("DrissionPage not installed — run: pip install DrissionPage")
        raise SystemExit(1)

    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)

    co = ChromiumOptions()
    co.headless(False)  # Must be visible so you can log in
    co.set_argument("--window-size=1200,800")
    co.set_argument("--disable-blink-features=AutomationControlled")

    print("Opening browser...")
    page = ChromiumPage(addr_or_opts=co)
    page.get("https://in.indeed.com/account/login")

    print()
    print("═" * 50)
    print("  Log in to Indeed in the browser window.")
    print("  Complete CAPTCHA and 2FA if prompted.")
    print("  Once you see the Indeed homepage/dashboard,")
    print("  press Enter here to save your session.")
    print("═" * 50)
    input("\n  Press Enter after you've logged in: ")

    # Save all cookies
    cookies = page.cookies()
    with open(COOKIES_PATH, "w") as f:
        json.dump(cookies, f, indent=2)

    page.quit()
    print(f"\n  Session saved → {COOKIES_PATH}")
    print("  You can now run the pipeline overnight.")
    print("  Re-run this script if Indeed asks you to log in again.")


if __name__ == "__main__":
    main()
