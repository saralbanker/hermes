"""
sources_wwr.py — We Work Remotely (WWR) job scraper and ATS resolver.

Uses public category RSS feeds to discover engineering jobs without auth or bot risk.
Extracts direct employer ATS application links (Greenhouse, Lever, etc.) where available.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from redirect_resolver import ats_from_url

ROOT = Path(__file__).parent.parent
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"}

WWR_RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]

COLUMNS = [
    "job_url", "company", "title", "location", "site", "description",
    "min_amount", "max_amount", "currency", "date_posted",
    "apply_channel", "ats_meta"
]


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def parse_wwr_rss(xml_content: str | bytes) -> list[dict[str, Any]]:
    """Parse WWR XML RSS feed into normalized job records."""
    jobs: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_content)
    except Exception as exc:
        print(f"[wwr] XML parse error: {exc}")
        return jobs

    channel = root.find("channel")
    if channel is None:
        return jobs

    for item in channel.findall("item"):
        raw_title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or item.findtext("guid") or "").strip()
        region = (item.findtext("region") or "Anywhere in the World").strip()
        desc_html = item.findtext("description") or ""
        pub_date = (item.findtext("pubDate") or "").strip()

        if not link or not raw_title:
            continue

        company = "Unknown"
        title = raw_title
        if ": " in raw_title:
            parts = raw_title.split(": ", 1)
            company, title = parts[0].strip(), parts[1].strip()

        location = f"Remote, {region}" if "remote" not in region.lower() else region

        # Attempt to find direct ATS link in description if present
        apply_channel = "redirect"
        ats_meta = None
        for ats_domain in ("greenhouse.io", "lever.co"):
            m = re.search(r'https?://[^\s"\'<>]*' + re.escape(ats_domain) + r'/[^\s"\'<>]*', desc_html)
            if m:
                ats_info = ats_from_url(m.group(0))
                if ats_info:
                    apply_channel, ats_meta = ats_info
                    break

        jobs.append({
            "job_url": link,
            "company": company,
            "title": title,
            "location": location,
            "site": "wwr",
            "description": strip_html(desc_html),
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "date_posted": pub_date,
            "apply_channel": apply_channel,
            "ats_meta": ats_meta,
        })
    return jobs


def fetch_wwr_jobs(cfg: dict, limit: int | None = None) -> pd.DataFrame:
    """Fetch all programming jobs from We Work Remotely category RSS feeds."""
    max_jobs = limit or cfg.get("search", {}).get("results_wanted", 40)
    all_jobs: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for feed_url in WWR_RSS_FEEDS:
        try:
            resp = requests.get(feed_url, headers=UA, timeout=20)
            if resp.status_code != 200:
                print(f"[wwr] feed returned {resp.status_code}: {feed_url}")
                continue
            feed_jobs = parse_wwr_rss(resp.content)
            for j in feed_jobs:
                if j["job_url"] not in seen_urls:
                    seen_urls.add(j["job_url"])
                    all_jobs.append(j)
        except Exception as exc:
            print(f"[wwr] error fetching {feed_url}: {exc}")

    df = pd.DataFrame(all_jobs, columns=COLUMNS)
    if not df.empty:
        df = df.drop_duplicates(subset=["job_url"]).reset_index(drop=True)
    print(f"[discover] WWR: {len(df)} jobs from RSS feeds")
    return df
