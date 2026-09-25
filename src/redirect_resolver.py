"""
redirect_resolver.py — Find where a job board's "Apply" button really leads.

Himalayas / Remotive / RemoteOK list jobs but host no application form: their
Apply button redirects (often through a click tracker) to the employer's ATS.
This module opens the listing in a real Chrome window, clicks Apply and
captures the final URL. If that URL is a Greenhouse / Lever / Ashby posting,
ats_from_url() turns it into the ats_meta JSON that ats_apply.py consumes.

    resolve_apply_target(listing_url) -> {"final_url", "ats_meta" | None, "error" | None}

Browser pattern: headful Chrome inside a private Xvfb display
(display.ensure_virtual_display()). Headless Chrome is served Cloudflare
challenges on these boards; a real window passes them. On KDE Wayland a
headful window cannot be parked off-screen (Wayland ignores window-position),
so it gets its own private X display instead — see display.py.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from display import ensure_virtual_display

ROOT = Path(__file__).parent.parent
PROFILE_DIR = ROOT / "output" / "chrome-redirect-profile"
CDP_PORT = 9377          # distinct from indeed_apply's browser so both can coexist
PAGE_LOAD_TIMEOUT = 30
REDIRECT_SETTLE_SECONDS = 6

GREENHOUSE_RE = re.compile(
    r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)"
    r"(?:/jobs/|[?&]token=|[?&]gh_jid=)(\d+)", re.I)
LEVER_RE = re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w.-]+)/([0-9a-f-]{36})", re.I)
ASHBY_RE = re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", re.I)

APPLY_TEXT_XPATH = (
    'xpath://*[self::a or self::button][contains(translate(normalize-space(.), '
    '"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "apply")]'
)
APPLY_LABEL_RE = re.compile(r"^(apply|easy apply|quick apply)\b")


# ---------------------------------------------------------------------------
# URL → ATS metadata
# ---------------------------------------------------------------------------

def _meta(ats: str, token: str, job_id: str, apply_url: str) -> str:
    """Same JSON shape as sources_ats._meta, so ats_apply treats both identically."""
    return json.dumps({"ats": ats, "token": token, "job_id": job_id, "apply_url": apply_url})


def ats_from_url(url: str | None) -> tuple[str, str] | None:
    """(apply_channel, ats_meta) when url points at a supported ATS posting, else None."""
    if not url:
        return None
    m = GREENHOUSE_RE.search(url)
    if m:
        token, job_id = m.group(1), m.group(2)
        return "greenhouse", _meta("greenhouse", token, job_id,
                                   f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={job_id}")
    m = LEVER_RE.search(url)
    if m:
        token, job_id = m.group(1), m.group(2)
        return "lever", _meta("lever", token, job_id, f"https://jobs.lever.co/{token}/{job_id}/apply")
    m = ASHBY_RE.search(url)
    if m:
        token, job_id = m.group(1), m.group(2)
        return "ashby", _meta("ashby", token, job_id,
                              f"https://jobs.ashbyhq.com/{token}/{job_id}/application")
    return None


def _ats_from_page(url: str, html: str) -> tuple[str, str] | None:
    """Company careers pages often embed the ATS form in an iframe (?gh_jid=, lever embeds)."""
    found = ats_from_url(url)
    if found:
        return found
    for pattern in (GREENHOUSE_RE, LEVER_RE, ASHBY_RE):
        m = pattern.search(html or "")
        if m:
            return ats_from_url(m.group(0))
    return None


SIGNUP_WALL_RE = re.compile(r"/sign-?up(/|\?|$)|/register(/|\?|$)|/create-account(/|\?|$)", re.I)


def describe_host(url: str) -> str:
    """Short reason text for an unsupported destination, e.g. 'workable.com'."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if "gh_jid" in parse_qs(urlparse(url).query):
        return f"{host} (greenhouse on company site, board token unknown)"
    return host or "unknown"


def _account_wall(listing_url: str, final_url: str) -> bool:
    """True when Apply redirected to the board's OWN signup flow rather than an
    employer form (verified live: Himalayas sends some listings to
    himalayas.app/signup/talent?redirect=... — creating an account is out of scope)."""
    same_host = urlparse(final_url).netloc == urlparse(listing_url).netloc
    return same_host and bool(SIGNUP_WALL_RE.search(urlparse(final_url).path))


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

def _open_browser():
    from DrissionPage import ChromiumOptions, ChromiumPage

    ensure_virtual_display()  # headful Chrome inside a private Xvfb display — see display.py
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    co = ChromiumOptions()
    co.headless(False)
    co.set_argument("--window-size=1366,900")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_user_data_path(str(PROFILE_DIR))
    co.set_local_port(CDP_PORT)
    page = ChromiumPage(addr_or_opts=co)
    page.set.timeouts(base=10, page_load=PAGE_LOAD_TIMEOUT, script=10)
    return page


# Himalayas job pages carry a site-wide sponsored banner ("aiapply.co?utm_source=...")
# whose link text also matches "apply"; without this it consistently outranks the job's
# own Apply button (verified live: two different Himalayas listings both resolved to the
# identical aiapply.co?utm_campaign=... URL). A tracking-parameter href is strong evidence
# of an ad, not a per-job application action.
AD_HREF_RE = re.compile(r"[?&]utm_(source|medium|campaign|content)=", re.I)
PROMO_THIN_PATH_CHARS = 20  # aiapply.co's ad banner path is 0 chars; a real job path is 20+


def _looks_like_promo_redirect(url: str) -> bool:
    """A tracking-parameter URL is only treated as a sponsored/ad link when its path is
    also thin (near-root) — e.g. aiapply.co's banner (`/`, 0 chars) or lemon.io's agency
    landing page (`/for-developers/`, 14 chars). A legitimate employer apply link routinely
    carries the SAME utm_source=indeed_integration Indeed itself attaches to "Apply on
    company site" redirects (verified live: careers.avalara.com/careers-home/jobs/17244/job
    — a real per-job path, 28 chars) and must not be misclassified as an ad."""
    if not AD_HREF_RE.search(url):
        return False
    return len(urlparse(url).path.strip("/")) < PROMO_THIN_PATH_CHARS


def _find_apply(page):
    """The most specific Apply control on the listing page, or None."""
    board_host = urlparse(page.url).netloc

    def rank(ele) -> int:
        text = " ".join((ele.text or "").split()).lower()
        href = ele.attr("href") or ""
        score = 0 if APPLY_LABEL_RE.match(text) and len(text) <= 40 else 2  # promo banners mention "apply" too
        if not (href.startswith("http") and urlparse(href).netloc != board_host):
            score += 1  # prefer links that leave the board
        if AD_HREF_RE.search(href):
            score += 10  # sponsored banner, not the job's own apply action — last resort only
        return score

    visible = [e for e in page.eles(APPLY_TEXT_XPATH, timeout=5) if e.states.is_displayed]
    return min(visible, key=rank) if visible else None


def _follow_apply(page, listing_url: str) -> tuple:
    """Click Apply and return the URL the browser ends on (new tab or same tab)."""
    button = _find_apply(page)
    if button is None:
        raise LookupError("apply_button_not_found")
    tabs_before = page.tab_ids
    href = button.attr("href") or ""
    if href.startswith("http") and button.attr("target") != "_blank":
        page.get(href)
    else:
        button.click(by_js=True)
    time.sleep(REDIRECT_SETTLE_SECONDS)
    new_tabs = [t for t in page.tab_ids if t not in tabs_before]
    target = page.get_tab(new_tabs[0]) if new_tabs else page
    final_url = target.url
    if final_url.rstrip("/") == listing_url.rstrip("/"):
        raise LookupError("apply_click_did_not_navigate")
    return final_url, target


def _classify_destination(source_url: str, final_url: str, html: str) -> dict:
    """Common tail once a click or redirect has landed somewhere: shared by
    resolve_apply_target (board Apply buttons) and resolve_indeed_external (Indeed's own
    'Apply on company site' redirect) — both need the same ATS / account-wall /
    sponsored-link classification once they have a final_url."""
    found = _ats_from_page(final_url, html)
    if found:
        return {"final_url": final_url, "channel": found[0], "ats_meta": found[1], "error": None}
    if _account_wall(source_url, final_url):
        return {"final_url": final_url, "channel": None, "ats_meta": None,
                "error": f"account_required:{describe_host(final_url)} requires creating an account to apply"}
    if _looks_like_promo_redirect(final_url):
        # A tracked/sponsored link, not a real per-job apply action. Caller must not hand
        # this off to the direct-form engine as if it were the employer's own form.
        return {"final_url": final_url, "channel": None, "ats_meta": None,
                "error": f"sponsored_link:{describe_host(final_url)} (tracked link, not a job application)"}
    return {"final_url": final_url, "channel": None, "ats_meta": None,
            "error": f"unsupported_destination:{describe_host(final_url)}"}


def _quit_browser(page) -> None:
    if page is None:
        return
    try:
        page.quit()
    except Exception as exc:  # already dead — nothing left to clean up
        print(f"  [redirect] browser quit failed: {exc}")


def resolve_apply_target(listing_url: str) -> dict:
    """Open the listing, click Apply, classify the destination. Never raises."""
    direct = ats_from_url(listing_url)
    if direct:  # Himalayas often stores the ATS link itself as the listing URL
        return {"final_url": listing_url, "channel": direct[0], "ats_meta": direct[1], "error": None}
    page = None
    try:
        page = _open_browser()
        page.get(listing_url)
        time.sleep(2.0)  # let React-hydrated listings finish rendering before scanning for Apply
        final_url, target = _follow_apply(page, listing_url)
        return _classify_destination(listing_url, final_url, target.html)
    except LookupError as exc:
        return {"final_url": None, "channel": None, "ats_meta": None, "error": str(exc)}
    except Exception as exc:  # browser/CDP failures: report and let the pipeline continue
        return {"final_url": None, "channel": None, "ats_meta": None,
                "error": f"redirect_browser_error:{type(exc).__name__}: {str(exc)[:160]}"}
    finally:
        _quit_browser(page)


def resolve_indeed_external(url: str) -> dict:
    """Follow Indeed's own 'Apply on company site' link (e.g. /applystart?jk=...) to find
    where it really lands. Indeed blocks a plain HTTP GET of this URL (403, the same
    Cloudflare protection as its other pages — verified live), so this needs the same real
    browser hop as an aggregator redirect. Unlike resolve_apply_target, `url` IS the
    redirect already: there is no separate Apply button to find and click first."""
    page = None
    try:
        page = _open_browser()
        page.get(url, timeout=PAGE_LOAD_TIMEOUT)
        time.sleep(REDIRECT_SETTLE_SECONDS)
        return _classify_destination(url, page.url, page.html)
    except Exception as exc:  # browser/CDP failures: report and let the pipeline continue
        return {"final_url": None, "channel": None, "ats_meta": None,
                "error": f"redirect_browser_error:{type(exc).__name__}: {str(exc)[:160]}"}
    finally:
        _quit_browser(page)


if __name__ == "__main__":
    import sys
    print(json.dumps(resolve_apply_target(sys.argv[1]), indent=2))
