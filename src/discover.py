"""
discover.py — Scrape job listings and save new ones to SQLite.

Sources (enable in config.search.boards):
  - indeed      python-jobspy, remote search + on-site search around Ahmedabad
  - ats         Greenhouse / Lever / Ashby public board APIs (src/sources_ats.py)
  - himalayas   Himalayas API, filtered server-side to jobs open to India
  - remotive    Remotive public JSON API
  - remoteok    RemoteOK public JSON API

Every scraped job passes through filters.passes_filters() (location, staleness,
tier/role, salary). Rejected jobs are stored as status='filtered' (or 'expired'
for stale postings) with the reason, so they are deduplicated on later runs
instead of re-evaluated. Cross-board duplicates (same company + normalised
title) are skipped before being written at all.

Usage:
    python src/discover.py [--dry-run] [--limit N]

    --dry-run   Scrape + dedup but do NOT write to DB; just print counts.
    --limit N   Override results_wanted per role (default: from config).
"""

import argparse
import html
import re
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, upsert_job, update_job, get_all_urls, get_conn, dedupe_key as make_dedupe_key  # noqa: E402
from filters import passes_filters, classify_tier  # noqa: E402

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Read config.yaml relative to this file's project root."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_all_roles(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """
    Iterate cfg["search"]["target_roles"], call JobSpy for each role,
    return a single combined DataFrame.  Sleeps 2 s between roles.
    """
    from jobspy import scrape_jobs

    search = cfg["search"]
    roles = search["target_roles"]
    boards = search.get("boards", ["indeed"])
    results_wanted = limit if limit is not None else search.get("results_wanted", 30)
    hours_old = search.get("hours_old", 72)
    location = search.get("location", "Remote")
    country_indeed = search.get("country_indeed", "India")

    print(f"[discover] Scraping {len(roles)} roles on {boards}...")
    if "linkedin" in boards:
        print("[discover] WARNING: linkedin scraping enabled — apply is disabled for it (ban risk)")

    frames: list[pd.DataFrame] = []

    jobspy_boards = [b for b in boards if b in ("indeed", "linkedin")]
    if not jobspy_boards:
        return pd.DataFrame()
    local_location = search.get("local_location")
    radius_miles = int(cfg["geo"]["radius_km"] / 1.609)
    searches = [(role, location, None) for role in roles]
    if local_location:
        searches += [(role, local_location, radius_miles) for role in roles[:4]]

    for i, (role, where, distance) in enumerate(searches):
        print(f"[discover] [{i+1}/{len(searches)}] Scraping '{role}' @ {where}...", flush=True)
        try:
            df = scrape_jobs(
                site_name=jobspy_boards,
                search_term=role,
                location=where,
                distance=distance or 50,
                is_remote=distance is None,
                results_wanted=results_wanted,
                hours_old=hours_old,
                country_indeed=country_indeed,
                linkedin_fetch_description=("linkedin" in jobspy_boards),
            )
            if df is not None and not df.empty:
                frames.append(df)
                print(f"[discover] [{i+1}/{len(searches)}] '{role}' — {len(df)} results", flush=True)
            else:
                print(f"[discover] [{i+1}/{len(searches)}] '{role}' — 0 results", flush=True)
        except Exception as exc:
            print(f"[discover] WARNING: scraping '{role}' failed — {exc}")

        # Rate-limit between searches (skip sleep after the last one)
        if i < len(searches) - 1:
            time.sleep(2)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Free public API scrapers (zero bot risk)
# ---------------------------------------------------------------------------

def _normalize_tags(tags) -> str:
    if not tags:
        return ""
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags)
    return str(tags)


def scrape_remoteok(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """Fetch jobs from RemoteOK public JSON API — no auth, no bot risk."""
    keywords = cfg["search"].get("target_roles", [])
    max_jobs = limit or cfg["search"].get("results_wanted", 30)

    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-seeker)"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[discover] RemoteOK API error: {exc}")
        return pd.DataFrame()

    # First element is a legal notice dict, skip it
    jobs = [j for j in data if isinstance(j, dict) and "id" in j]

    # Filter by keywords
    kw_lower = [k.lower() for k in keywords]
    filtered = []
    for job in jobs:
        title = (job.get("position", "") or "").lower()
        tags  = _normalize_tags(job.get("tags", [])).lower()
        if any(kw in title or kw in tags for kw in kw_lower):
            filtered.append(job)

    rows = []
    for job in filtered[:max_jobs]:
        rows.append({
            "job_url":     f"https://remoteok.com/remote-jobs/{job.get('slug', job.get('id', ''))}",
            "company":     job.get("company", "Unknown"),
            "title":       job.get("position", "Unknown"),
            "location":    f"Remote, {job.get('location') or 'Worldwide'}",
            "site":        "remoteok",
            "description": job.get("description", ""),
            "min_amount":  job.get("salary_min") or None,
            "max_amount":  job.get("salary_max") or None,
            "currency":    "USD",
            "date_posted": job.get("date", ""),
        })

    print(f"[discover] RemoteOK: {len(rows)} matching jobs")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def scrape_remotive(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """Fetch jobs from Remotive public JSON API — no auth, no bot risk."""
    keywords = cfg["search"].get("target_roles", [])
    max_jobs = limit or cfg["search"].get("results_wanted", 30)

    frames = []
    for kw in keywords[:4]:  # cap API calls; Remotive is generous but polite
        try:
            resp = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": kw, "limit": max_jobs},
                headers={"User-Agent": "Mozilla/5.0 (compatible; job-seeker)"},
                timeout=20,
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
            for job in jobs:
                frames.append({
                    "job_url":     job.get("url", ""),
                    "company":     job.get("company_name", "Unknown"),
                    "title":       job.get("title", "Unknown"),
                    "location":    f"Remote, {job.get('candidate_required_location') or 'Worldwide'}",
                    "site":        "remotive",
                    "description": job.get("description", ""),
                    "min_amount":  None,
                    "max_amount":  None,
                    "date_posted": job.get("publication_date", ""),
                })
            time.sleep(1)
        except Exception as exc:
            print(f"[discover] Remotive error for '{kw}': {exc}")

    df = pd.DataFrame(frames) if frames else pd.DataFrame()
    # Drop empty URLs and deduplicate within this batch
    if not df.empty:
        df = df[df["job_url"].astype(str).str.startswith("http")]
        df = df.drop_duplicates(subset=["job_url"])
        df = df.head(max_jobs)
    print(f"[discover] Remotive: {len(df)} matching jobs")
    return df


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate(df: pd.DataFrame, existing_urls: set) -> pd.DataFrame:
    """Drop rows whose job_url is already in existing_urls."""
    if df.empty:
        return df
    mask = ~df["job_url"].isin(existing_urls)
    return df[mask].reset_index(drop=True)


def get_all_dedupe_keys() -> set:
    """Every dedupe_key already stored, any status — cross-board dedupe before any LLM time."""
    conn = get_conn()
    rows = conn.execute("SELECT dedupe_key FROM jobs WHERE dedupe_key IS NOT NULL "
                        "AND status NOT IN ('filtered', 'expired')").fetchall()
    conn.close()
    return {r["dedupe_key"] for r in rows}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _safe_str(value, default: str | None = None) -> str | None:
    """Return str(value) if value is not NaN/None, else default."""
    if pd.isna(value):
        return default
    s = str(value).strip()
    return s if s else default


def _safe_int(value) -> int | None:
    """Return int(value) if value is a valid, non-NaN number, else None."""
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# Where each source's application form lives. 'redirect' = the listing page links
# out to the employer's ATS; apply.py resolves it in a real browser at apply time.
CHANNEL_BY_SITE = {
    "indeed": "indeed", "greenhouse": "greenhouse", "lever": "lever", "ashby": "ashby",
    "himalayas": "redirect", "remotive": "redirect", "remoteok": "redirect", "linkedin": "none",
    "wwr": "redirect", "arbeitnow": "redirect",
}


def _row_to_job(row) -> dict:
    site = _safe_str(getattr(row, "site", None), "") or ""
    return {
        "url":           _safe_str(getattr(row, "job_url", None), ""),
        "company":       _safe_str(getattr(row, "company", None), "Unknown"),
        "title":         _safe_str(getattr(row, "title", None), "Unknown"),
        "location":      _safe_str(getattr(row, "location", None)),
        "job_board":     site,
        "description":   _strip_html(_safe_str(getattr(row, "description", None)) or ""),
        "salary_min":    _safe_int(getattr(row, "min_amount", None)),
        "salary_max":    _safe_int(getattr(row, "max_amount", None)),
        "currency":      _safe_str(getattr(row, "currency", None)),
        "date_posted":   _safe_str(getattr(row, "date_posted", None)),
        "apply_channel": _safe_str(getattr(row, "apply_channel", None)) or CHANNEL_BY_SITE.get(site, "none"),
        "ats_meta":      _safe_str(getattr(row, "ats_meta", None)),
    }


def _strip_html(text: str) -> str:
    if "<" not in text:
        return text
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def save_to_db(df: pd.DataFrame, cfg: dict) -> tuple[int, int, int]:
    """
    Filter each row (location / staleness / tier / salary) and save it.
    Cross-board duplicates (same company + normalised title, any status) are
    skipped before any LLM time — one application per role regardless of
    which board listed it.
    Returns (eligible_saved, filtered_saved, dedupe_skipped).
    """
    eligible = filtered = dedupe_skipped = 0
    seen_keys = get_all_dedupe_keys()
    for row in df.itertuples(index=False):
        job = _row_to_job(row)
        if not job["url"]:
            continue

        key = make_dedupe_key(job.get("company"), job.get("title"))
        if key in seen_keys:
            dedupe_skipped += 1
            continue

        ok, reason = passes_filters(job, cfg)
        if ok:  # only an eligible listing claims the role; an on-site twin must not block a remote one
            seen_keys.add(key)
        tier, years, _tier_reason = classify_tier(
            job.get("title") or "", job.get("description") or "", cfg)
        job.pop("currency")
        if ok:
            job.update(location_reason=reason)
        elif reason == "expired":
            job.update(status="expired", status_reason=reason)
        else:
            job.update(status="filtered", status_reason=reason)

        rowid = upsert_job(job)
        if rowid:
            update_job(job["url"], {"tier": tier, "required_years": years, "dedupe_key": key})
            eligible += ok
            filtered += not ok
    return eligible, filtered, dedupe_skipped


def scrape_himalayas(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """Himalayas search API, restricted server-side to jobs hiring in India."""
    per_role = limit or cfg["search"].get("results_wanted", 30)
    rows = []
    for kw in cfg["search"]["target_roles"]:
        try:
            resp = requests.get(
                "https://himalayas.app/jobs/api/search",
                params={"q": kw, "country": "India", "sort": "recent", "limit": min(per_role, 20)},
                headers={"User-Agent": "Mozilla/5.0 (compatible; job-seeker)"},
                timeout=20,
            )
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"[discover] Himalayas error for '{kw}': {exc}")
            continue
        for job in jobs:
            regions = job.get("locationRestrictions") or ["Worldwide"]
            rows.append({
                "job_url":     job.get("applicationLink") or job.get("guid", ""),
                "company":     job.get("companyName", "Unknown"),
                "title":       job.get("title", "Unknown"),
                "location":    "Remote, " + ", ".join(regions),
                "site":        "himalayas",
                "description": job.get("description", ""),
                "min_amount":  job.get("minSalary"),
                "max_amount":  job.get("maxSalary"),
                "currency":    job.get("currency"),
                "date_posted": str(job.get("pubDate", "")),
            })
        time.sleep(1)
    df = pd.DataFrame(rows).drop_duplicates(subset=["job_url"]) if rows else pd.DataFrame()
    print(f"[discover] Himalayas: {len(df)} jobs open to India")
    return df


def _scrape_ats(cfg: dict) -> pd.DataFrame:
    from sources_ats import fetch_ats_jobs
    return fetch_ats_jobs(cfg)


def _scrape_wwr(cfg: dict, limit: int | None) -> pd.DataFrame:
    from sources_wwr import fetch_wwr_jobs
    return fetch_wwr_jobs(cfg, limit)


def _scrape_arbeitnow(cfg: dict, limit: int | None) -> pd.DataFrame:
    from sources_arbeitnow import fetch_arbeitnow_jobs
    return fetch_arbeitnow_jobs(cfg, limit)


SCRAPERS = {
    "ats": lambda cfg, limit: _scrape_ats(cfg),
    "wwr": _scrape_wwr,
    "arbeitnow": _scrape_arbeitnow,
    "himalayas": scrape_himalayas,
    "remotive": scrape_remotive,
    "remoteok": scrape_remoteok,
}


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def collect(cfg: dict, limit: int | None) -> pd.DataFrame:
    """Run every enabled scraper. One source failing never stops the others."""
    boards = cfg["search"].get("boards", ["indeed"])
    frames = [scrape_all_roles(cfg, limit=limit)]
    for name, scraper in SCRAPERS.items():
        if name not in boards:
            continue
        try:
            frames.append(scraper(cfg, limit))
        except Exception as exc:  # a broken source must not kill discovery
            print(f"[discover] WARNING: source '{name}' failed — {type(exc).__name__}: {exc}")
    frames = [f for f in frames if f is not None and not f.empty]
    raw_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not raw_df.empty and "job_url" in raw_df.columns:
        raw_df = raw_df.dropna(subset=["job_url"])
        raw_df = raw_df[raw_df["job_url"].astype(str).str.strip() != ""]
        raw_df = raw_df.drop_duplicates(subset=["job_url"])
    return raw_df


def main(dry_run: bool = False, limit: int | None = None):
    t0 = time.time()
    cfg = load_config()
    init_db()

    raw_df = collect(cfg, limit)
    raw_count = len(raw_df)
    print(f"[discover] Found {raw_count} raw jobs total")
    if raw_count == 0:
        print("[discover] Nothing scraped — done.")
        return

    new_df = deduplicate(raw_df, get_all_urls())
    print(f"[discover] {raw_count - len(new_df)} already in DB, skipping")

    if dry_run:
        print(f"[discover] --dry-run active: would evaluate {len(new_df)} new jobs (not written)")
    else:
        eligible, filtered, dedupe_skipped = save_to_db(new_df, cfg)
        print(f"[discover] Saved {eligible} eligible jobs, {filtered} filtered out "
              f"(location/tier/salary/stale), {dedupe_skipped} skipped (cross-board duplicate)")

    print(f"[discover] Done in {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape job listings and save to SQLite."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape + dedup but do NOT write to DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Override results_wanted per role (default: from config).",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit)
