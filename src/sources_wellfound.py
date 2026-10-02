"""
sources_wellfound.py — Wellfound (formerly AngelList Talent) job scraper.

IMPLEMENTATION_ROADMAP.md §82 (M8 — Wellfound): "Treat Wellfound as unproven until live
evidence exists." This module is the discovery half of that investigation's answer.

What was checked before writing any code here (read-only, logged-out reconnaissance against
public pages only — no login, no challenge solving, no stored session):

  1. robots.txt (https://wellfound.com/robots.txt) disallows /_jobs/, /jobs/applications,
     /jobs/signup, /search, and several query-parameter variants (?jobId=, ?role=, etc.), but
     does NOT disallow a plain job detail path (/jobs/<id>-<slug>) or the public listing
     index (/jobs) — those are exactly what this module reads.
  2. A plain `requests.get()` with an ordinary browser User-Agent (no stealth, no fingerprint
     evasion, no cookies/session) against https://wellfound.com/jobs and several individual
     /jobs/<id>-<slug> pages returned a normal HTTP 200 with real HTML every time — no
     Cloudflare "Just a moment" / challenge-platform interstitial, no login redirect. This is
     the same request shape sources_wwr.py already uses for weworkremotely.com.
  3. Every job detail page embeds a `<script type="application/ld+json">` block with
     `@type: "JobPosting"` (schema.org) — title, hiringOrganization, jobLocation, datePosted,
     employmentType, baseSalary, and the full description — explicitly public, structured,
     search-engine-facing data (MASTER_PLAN.md §6.1: "legitimate public/structured read
     path"), the same category of source as src/sources_wwr.py's RSS feeds, not a private or
     reverse-engineered API.

  Conclusion: reading listings is legitimate and does not require defeating anything —
  fetch_wellfound_jobs() below does exactly that, nothing more.

The DIFFERENT, harder finding — why this source still cannot drive a submission on its own
today — is on the APPLY side, not discovery: every JobPosting sampled during this
investigation (5/5, across multiple categories) carried `"directApply": true`, meaning the
posting's only "Apply" action is Wellfound's own authenticated one-click-apply flow, not a
link out to the employer's ATS/career page. Logging into that flow is out of scope (no
Wellfound/AngelList credentials exist anywhere in this repo — checked config.yaml, the
process environment, and output/hermes.env — and this project does not automate logins or
bypass access controls per IMPLEMENTATION_ROADMAP.md §82/§84). `apply_channel` is set to
WELLFOUND_DIRECT_APPLY below for exactly this case, carrying `ats_meta={"direct_apply_only":
true}` forward so src/engine_apply.py's shared redirect-route resolver
(_resolve_redirect_route) can recognize it and record a clean, immediate NO_SUPPORTED_ROUTE
outcome — without ever opening a browser against wellfound.com at apply time. A posting that
instead embeds an inline Greenhouse/Lever link in its description (checked the same way
src/sources_wwr.py already does, via redirect_resolver.ats_from_url), or that is one day
observed with `directApply: false` (none were, in this sample — the code does not assume
there are none), is tagged normally and flows through the ordinary redirect-resolution path.
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from redirect_resolver import ats_from_url

ROOT = Path(__file__).parent.parent
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}

WELLFOUND_JOBS_URL = "https://wellfound.com/jobs"
JOB_LINK_RE = re.compile(r'/jobs/(\d+-[a-z0-9-]+)', re.IGNORECASE)
JOB_DETAIL_FMT = "https://wellfound.com/jobs/{slug}"
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)
REQUEST_TIMEOUT = 20
DETAIL_FETCH_DELAY_SECONDS = 1.0  # same good-citizen pacing sources_wwr.py uses between feeds

# Sentinel apply_channel for a posting whose only Apply action is the source platform's own
# authenticated flow — never "redirect" (which implies an eventual external employer link may
# exist). src/discover.py's CHANNEL_BY_SITE has no special-case for this; it is only ever
# consumed by src/engine_apply.py's _resolve_redirect_route via the ats_meta it carries.
WELLFOUND_DIRECT_APPLY = "wellfound_direct"

COLUMNS = [
    "job_url", "company", "title", "location", "site", "description",
    "min_amount", "max_amount", "currency", "date_posted",
    "apply_channel", "ats_meta",
]


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def parse_job_links(listing_html: str) -> list[str]:
    """Job-detail slugs ("<id>-<title-slug>") found on a public listing/browse page,
    de-duplicated, order preserved."""
    seen: list[str] = []
    for slug in JOB_LINK_RE.findall(listing_html or ""):
        if slug not in seen:
            seen.append(slug)
    return seen


def _location_from_job_posting(data: dict) -> str:
    """JobPosting.jobLocation is a list of schema.org Place entries; jobLocationType ==
    "TELECOMMUTE" means remote-eligible (Wellfound sets this for remote roles alongside a
    real location, same as many ATS JobPosting feeds)."""
    is_remote = (data.get("jobLocationType") or "").upper() == "TELECOMMUTE"
    places = data.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    parts: list[str] = []
    if places:
        addr = (places[0] or {}).get("address") or {}
        parts = [addr.get(k) for k in ("addressLocality", "addressRegion", "addressCountry") if addr.get(k)]
    location = ", ".join(parts) if parts else None
    if is_remote:
        return f"Remote, {location}" if location else "Remote"
    return location or "Unknown"


def _salary_from_job_posting(data: dict) -> tuple[Any, Any, Any]:
    salary = data.get("baseSalary") or {}
    value = salary.get("value") or {}
    return value.get("minValue"), value.get("maxValue"), salary.get("currency")


def _resolve_apply_channel(description_html: str, direct_apply: bool | None) -> tuple[str, str | None]:
    """Same inline-ATS-link detection src/sources_wwr.py already does, checked first: an
    employer-managed Greenhouse/Lever link embedded in the description outranks Wellfound's
    own directApply flag regardless of its value (an inline ATS link is direct, verifiable
    evidence of a real external route; directApply is Wellfound's own UI hint, not a
    guarantee either way)."""
    for ats_domain in ("greenhouse.io", "lever.co"):
        m = re.search(r'https?://[^\s"\'<>]*' + re.escape(ats_domain) + r'/[^\s"\'<>]*', description_html)
        if m:
            found = ats_from_url(m.group(0))
            if found:
                return found
    if direct_apply:
        return WELLFOUND_DIRECT_APPLY, json.dumps({"direct_apply_only": True})
    return "redirect", None


def parse_job_posting(detail_html: str, listing_url: str) -> dict[str, Any] | None:
    """One job detail page's embedded schema.org JobPosting JSON-LD -> a normalized job
    record (same shape sources_wwr.py's parse_wwr_rss produces). Returns None if the page
    carries no JobPosting block (listing removed/expired, or a page shape this module
    does not recognize — never guessed at)."""
    m = JSON_LD_RE.search(detail_html or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return None
    if data.get("@type") != "JobPosting":
        return None

    title = data.get("title") or "Unknown"
    company = (data.get("hiringOrganization") or {}).get("name") or "Unknown"
    description_html = data.get("description") or ""
    min_amount, max_amount, currency = _salary_from_job_posting(data)
    apply_channel, ats_meta = _resolve_apply_channel(description_html, data.get("directApply"))

    return {
        "job_url": listing_url,
        "company": company,
        "title": title,
        "location": _location_from_job_posting(data),
        "site": "wellfound",
        "description": strip_html(description_html),
        "min_amount": min_amount,
        "max_amount": max_amount,
        "currency": currency,
        "date_posted": data.get("datePosted"),
        "apply_channel": apply_channel,
        "ats_meta": ats_meta,
    }


def fetch_wellfound_jobs(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """Fetch the public Wellfound job listing index, then each linked job's own public
    detail page, parsing its embedded JobPosting JSON-LD. Bounded by `limit` (or
    config.search.results_wanted) the same way fetch_wwr_jobs bounds its RSS read — this is
    a deliberately conservative, sequential, paced read (DETAIL_FETCH_DELAY_SECONDS between
    requests), not a crawl: one listing-index fetch plus up to `limit` detail fetches per
    discovery cycle."""
    max_jobs = limit or cfg.get("search", {}).get("results_wanted", 40)
    try:
        resp = requests.get(WELLFOUND_JOBS_URL, headers=UA, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"[wellfound] listing page returned {resp.status_code}")
            return pd.DataFrame(columns=COLUMNS)
    except requests.RequestException as exc:
        print(f"[wellfound] error fetching listing page: {exc}")
        return pd.DataFrame(columns=COLUMNS)

    slugs = parse_job_links(resp.text)[:max_jobs]
    rows: list[dict[str, Any]] = []
    for i, slug in enumerate(slugs):
        detail_url = JOB_DETAIL_FMT.format(slug=slug)
        try:
            detail_resp = requests.get(detail_url, headers=UA, timeout=REQUEST_TIMEOUT)
            if detail_resp.status_code != 200:
                print(f"[wellfound] job page returned {detail_resp.status_code}: {detail_url}")
                continue
            job = parse_job_posting(detail_resp.text, detail_url)
            if job is not None:
                rows.append(job)
        except requests.RequestException as exc:
            print(f"[wellfound] error fetching {detail_url}: {exc}")
        if i < len(slugs) - 1:
            time.sleep(DETAIL_FETCH_DELAY_SECONDS)

    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(subset=["job_url"]).reset_index(drop=True)
    print(f"[discover] Wellfound: {len(df)} jobs from public listing pages")
    return df
