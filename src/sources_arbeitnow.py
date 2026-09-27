"""
sources_arbeitnow.py — Arbeitnow remote jobs API adapter.

Free public JSON API. Automatically discovers remote engineering postings and
resolves the `/apply` endpoint via fast HTTP HEAD requests to determine
the underlying employer ATS (Greenhouse, Lever, etc.).
"""
from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from redirect_resolver import ats_from_url

ROOT = Path(__file__).parent.parent
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}

API_URL = "https://www.arbeitnow.com/api/job-board-api"

COLUMNS = [
    "job_url", "company", "title", "location", "site", "description",
    "min_amount", "max_amount", "currency", "date_posted",
    "apply_channel", "ats_meta"
]

ENGINEERING_KEYWORDS = re.compile(
    r"\b(software|engineer|engineering|developer|full[- ]?stack|back[- ]?end|front[- ]?end|"
    r"ai|ml|llm|machine learning|platform|sde|swe|devops|cloud|data|systems)\b",
    re.IGNORECASE,
)


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def resolve_apply_target_fast(job_url: str) -> tuple[str, str | None]:
    """Fast probe of Arbeitnow's /apply endpoint without browser rendering."""
    apply_url = job_url.rstrip("/") + "/apply"
    try:
        resp = requests.head(apply_url, headers=UA, allow_redirects=False, timeout=8)
        loc = resp.headers.get("Location")
        if loc:
            ats_info = ats_from_url(loc)
            if ats_info:
                return ats_info
    except Exception:
        pass
    return "redirect", None


def fetch_arbeitnow_jobs(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """Fetch remote engineering jobs from Arbeitnow public API."""
    max_pages = 2
    raw_jobs: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(f"{API_URL}?page={page}", headers=UA, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json().get("data", [])
            for j in data:
                is_remote = bool(j.get("remote")) or "remote" in (j.get("location") or "").lower()
                title = (j.get("title") or "").strip()
                if is_remote and ENGINEERING_KEYWORDS.search(title):
                    created_at = j.get("created_at")
                    dt_str = datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat() if created_at else ""
                    raw_jobs.append({
                        "job_url": j.get("url"),
                        "company": j.get("company_name", "Unknown"),
                        "title": title,
                        "location": "Remote, " + (j.get("location") or "Worldwide"),
                        "site": "arbeitnow",
                        "description": strip_html(j.get("description", "")),
                        "min_amount": None,
                        "max_amount": None,
                        "currency": None,
                        "date_posted": dt_str,
                        "apply_channel": "redirect",
                        "ats_meta": None,
                    })
        except Exception as exc:
            print(f"[arbeitnow] page {page} fetch error: {exc}")
            break

    if not raw_jobs:
        return pd.DataFrame(columns=COLUMNS)

    # Fast resolve apply destinations in parallel
    def _enrich(job: dict) -> dict:
        ch, meta = resolve_apply_target_fast(job["job_url"])
        job["apply_channel"] = ch
        job["ats_meta"] = meta
        return job

    with ThreadPoolExecutor(max_workers=6) as pool:
        enriched_jobs = list(pool.map(_enrich, raw_jobs))

    df = pd.DataFrame(enriched_jobs, columns=COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(subset=["job_url"]).reset_index(drop=True)
    print(f"[discover] Arbeitnow: {len(df)} remote engineering jobs")
    return df
