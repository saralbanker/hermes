"""
sources_ats.py — Engineering jobs from Greenhouse, Lever and Ashby public job-board APIs.

No auth, no scraping: these are the JSON APIs the companies' own career pages use.
Company board tokens live in data/ats_companies.yaml (refresh with
scripts/validate_ats_companies.py --probe).

Location and seniority filtering is NOT done here — discover.py applies it
centrally via geo.py so every source is filtered the same way.
"""
from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

import states

ROOT = Path(__file__).parent.parent
COMPANIES_PATH = ROOT / "data" / "ats_companies.yaml"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) hermes-job-search/1.0"}
MAX_DESC = 6000

ENGINEERING_TITLE = re.compile(
    r"\b(software|engineer|engineering|developer|full[- ]?stack|back[- ]?end|front[- ]?end|"
    r"ai|ml|llm|machine learning|platform|sde|swe|programmer|devops|sre)\b",
    re.IGNORECASE,
)
# Titles that match the pattern above but are not software-building roles.
NON_ENGINEERING_TITLE = re.compile(
    r"\b(sales|account executive|recruit|marketing|designer|counsel|legal|finance|"
    r"accountant|support specialist|customer success|manager, (sales|marketing)|"
    r"solutions? engineer|sales engineer|field engineer|mechanical|electrical|civil|"
    r"hardware|analog|rf engineer|manufacturing|technician)\b",
    re.IGNORECASE,
)

COLUMNS = [
    "job_url", "company", "title", "location", "site", "description", "min_amount",
    "max_amount", "currency", "date_posted", "apply_channel", "ats_meta",
]


def is_engineering_title(title: str) -> bool:
    return bool(ENGINEERING_TITLE.search(title)) and not NON_ENGINEERING_TITLE.search(title)


def html_to_text(raw: str | None) -> str:
    """Greenhouse double-escapes its HTML; unescape, strip tags, collapse whitespace."""
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:MAX_DESC]


def _get_json(url: str) -> dict | list | None:
    resp = requests.get(url, headers=UA, timeout=25)
    resp.raise_for_status()
    return resp.json()


def _meta(ats: str, token: str, job_id: str, apply_url: str) -> str:
    return json.dumps({"ats": ats, "token": token, "job_id": str(job_id), "apply_url": apply_url})


def _row(**kw) -> dict:
    return {col: kw.get(col) for col in COLUMNS}


# ---------------------------------------------------------------------------
# Per-ATS fetchers — each returns a list of row dicts for one company board
# ---------------------------------------------------------------------------

def fetch_greenhouse(token: str) -> list[dict]:
    data = _get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true&pay_transparency=true"
    )
    rows = []
    for j in data.get("jobs", []):
        if not is_engineering_title(j.get("title", "")):
            continue
        offices = [o.get("name", "") for o in j.get("offices", []) if o.get("name")]
        location = "; ".join(filter(None, [(j.get("location") or {}).get("name", "")] + offices))
        pay = (j.get("pay_input_ranges") or [None])[0] or {}
        rows.append(_row(
            job_url=j["absolute_url"], company=j.get("company_name") or token, title=j["title"],
            location=location, site="greenhouse", description=html_to_text(j.get("content")),
            min_amount=(pay.get("min_cents") or 0) // 100 or None,
            max_amount=(pay.get("max_cents") or 0) // 100 or None,
            currency=pay.get("currency_type"),
            date_posted=j.get("first_published") or j.get("updated_at"),
            apply_channel=states.CH_GREENHOUSE,
            # absolute_url is often the company's own careers page; the embed form
            # is Greenhouse-hosted and identical for every board.
            ats_meta=_meta("greenhouse", token, j["id"],
                           f"https://job-boards.greenhouse.io/embed/job_app?for={token}&token={j['id']}"),
        ))
    return rows


def _lever_salary(j: dict) -> tuple[int | None, int | None, str | None]:
    sr = j.get("salaryRange") or {}
    if not sr:
        return None, None, None
    factor = {"per-month-salary": 12, "per-hour-wage": 2080}.get(sr.get("interval", ""), 1)
    lo, hi = sr.get("min"), sr.get("max")
    return (lo * factor if lo else None), (hi * factor if hi else None), sr.get("currency")


def fetch_lever(token: str) -> list[dict]:
    data = _get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    rows = []
    for j in data if isinstance(data, list) else []:
        if not is_engineering_title(j.get("text", "")):
            continue
        cats = j.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location", "")]
        workplace = j.get("workplaceType") or ""
        location = "; ".join(filter(None, locations + ([workplace.capitalize()] if workplace else [])))
        lists = "\n".join(
            f"{li.get('text', '')}\n{html_to_text(li.get('content'))}" for li in j.get("lists", [])
        )
        desc = "\n".join(filter(None, [j.get("descriptionPlain"), lists, j.get("additionalPlain")]))
        lo, hi, cur = _lever_salary(j)
        created = datetime.fromtimestamp(j.get("createdAt", 0) / 1000, tz=timezone.utc).isoformat()
        rows.append(_row(
            job_url=j["hostedUrl"], company=token, title=j["text"], location=location, site="lever",
            description=desc[:MAX_DESC], min_amount=lo, max_amount=hi, currency=cur,
            date_posted=created, apply_channel=states.CH_LEVER,
            ats_meta=_meta("lever", token, j["id"], j.get("applyUrl") or j["hostedUrl"] + "/apply"),
        ))
    return rows


def _ashby_salary(j: dict) -> tuple[int | None, int | None, str | None]:
    for comp in ((j.get("compensation") or {}).get("summaryComponents") or []):
        if comp.get("compensationType") == "Salary" and comp.get("interval") == "1 YEAR":
            return comp.get("minValue"), comp.get("maxValue"), comp.get("currencyCode")
    return None, None, None


def fetch_ashby(token: str) -> list[dict]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    rows = []
    for j in data.get("jobs", []):
        if not j.get("isListed", True) or not is_engineering_title(j.get("title", "")):
            continue
        secondary = [s.get("location", "") for s in j.get("secondaryLocations") or []]
        remote = "Remote" if j.get("isRemote") or j.get("workplaceType") == "Remote" else ""
        location = "; ".join(filter(None, [j.get("location", "")] + secondary + [remote]))
        lo, hi, cur = _ashby_salary(j)
        rows.append(_row(
            job_url=j["jobUrl"], company=token, title=j["title"], location=location, site="ashby",
            description=(j.get("descriptionPlain") or "")[:MAX_DESC],
            min_amount=lo, max_amount=hi, currency=cur, date_posted=j.get("publishedAt"),
            apply_channel=states.CH_ASHBY,
            ats_meta=_meta("ashby", token, j["id"], j.get("applyUrl") or j["jobUrl"] + "/application"),
        ))
    return rows

# Ashby is disabled due to platform-side anti-bot blocking (blocked_antibot)
FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever}


def _fetch_one(pair: tuple[str, str]) -> list[dict]:
    ats, token = pair
    try:
        return FETCHERS[ats](token)
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        print(f"[discover] ATS {ats}/{token} failed — {type(exc).__name__}: {str(exc)[:120]}")
        return []


def fetch_ats_jobs(cfg: dict) -> pd.DataFrame:
    """All engineering postings from every configured ATS board, as a discover-style DataFrame."""
    companies = yaml.safe_load(COMPANIES_PATH.read_text()) or {}
    pairs = [(ats, t) for ats, tokens in companies.items() if ats in FETCHERS for t in tokens or []]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_fetch_one, pairs))
    rows = [r for batch in results for r in batch]
    companies_with_jobs = sum(1 for batch in results if batch)
    print(f"[discover] ATS: {len(rows)} jobs from {companies_with_jobs} companies")
    df = pd.DataFrame(rows, columns=COLUMNS)
    return df.drop_duplicates(subset=["job_url"]).reset_index(drop=True)
