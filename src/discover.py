"""
discover.py — Scrape job listings using python-jobspy and save new ones to SQLite.

Usage:
    python src/discover.py [--dry-run] [--limit N]

    --dry-run   Scrape + dedup but do NOT write to DB; just print counts.
    --limit N   Override results_wanted per role (default: from config).
"""

import argparse
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, upsert_job, get_all_urls  # noqa: E402

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
    results_wanted = limit if limit is not None else search.get("results_wanted", 30)
    hours_old = search.get("hours_old", 72)
    location = search.get("location", "Remote")
    country_indeed = search.get("country_indeed", "India")

    print(f"[discover] Scraping {len(roles)} roles across 4 boards...")

    frames: list[pd.DataFrame] = []

    for i, role in enumerate(roles):
        try:
            df = scrape_jobs(
                site_name=["linkedin", "indeed"],
                search_term=role,
                location=location,
                results_wanted=results_wanted,
                hours_old=hours_old,
                country_indeed=country_indeed,
                linkedin_fetch_description=True,
            )
            if df is not None and not df.empty:
                frames.append(df)
        except Exception as exc:
            print(f"[discover] WARNING: scraping '{role}' failed — {exc}")

        # Rate-limit between roles (skip sleep after the last role)
        if i < len(roles) - 1:
            time.sleep(2)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Drop rows with no job_url — they cannot be stored or deduped
    if "job_url" in combined.columns:
        combined = combined.dropna(subset=["job_url"])
        combined = combined[combined["job_url"].astype(str).str.strip() != ""]

    return combined


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate(df: pd.DataFrame, existing_urls: set) -> pd.DataFrame:
    """Drop rows whose job_url is already in existing_urls."""
    if df.empty:
        return df
    mask = ~df["job_url"].isin(existing_urls)
    return df[mask].reset_index(drop=True)


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


def save_to_db(df: pd.DataFrame) -> int:
    """
    Map JobSpy DataFrame columns to upsert_job() dict and save each row.
    Returns the number of rows actually inserted (IGNORE skips duplicates).
    """
    saved = 0
    for row in df.itertuples(index=False):
        job = {
            "url":          _safe_str(getattr(row, "job_url", None), ""),
            "company":      _safe_str(getattr(row, "company", None), "Unknown"),
            "title":        _safe_str(getattr(row, "title", None), "Unknown"),
            "location":     _safe_str(getattr(row, "location", None)),
            "job_board":    _safe_str(getattr(row, "site", None)),
            "description":  _safe_str(getattr(row, "description", None)),
            "salary_min":   _safe_int(getattr(row, "min_amount", None)),
            "salary_max":   _safe_int(getattr(row, "max_amount", None)),
            "date_posted":  _safe_str(getattr(row, "date_posted", None)),
        }
        if not job["url"]:
            continue
        rowid = upsert_job(job)
        if rowid:
            saved += 1
    return saved


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main(dry_run: bool = False, limit: int | None = None):
    t0 = time.time()

    cfg = load_config()
    init_db()

    # Scrape
    raw_df = scrape_all_roles(cfg, limit=limit)
    raw_count = len(raw_df)
    print(f"[discover] Found {raw_count} raw jobs")

    if raw_count == 0:
        print("[discover] Nothing scraped — done.")
        return

    # Dedup against existing DB records
    existing_urls = get_all_urls()
    new_df = deduplicate(raw_df, existing_urls)
    skip_count = raw_count - len(new_df)
    print(f"[discover] {skip_count} already in DB, skipping")

    if dry_run:
        print(f"[discover] --dry-run active: would save {len(new_df)} new jobs (not written)")
    else:
        saved = save_to_db(new_df)
        print(f"[discover] Saved {saved} new jobs")

    elapsed = time.time() - t0
    print(f"[discover] Done in {elapsed:.1f}s")


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
