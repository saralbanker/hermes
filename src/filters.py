"""
filters.py — Cheap deterministic job filters applied before any LLM call.

    passes_filters(job, cfg) -> (bool, reason)

Checks, in order: location (geo.py), staleness, seniority, salary floor.
Every rejection carries a reason string that is stored in jobs.status_reason,
so `tracker.py` can show why jobs were dropped.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from geo import is_location_eligible

SENIOR_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head|director|manager|architect|vp|"
    r"chief|distinguished|sde[- ]?(iii|3)|l[5-9]\b|engineer (iii|iv|3|4))", re.I)
NON_ENGINEERING_RE = re.compile(
    r"\b(sales|account executive|recruiter|marketing|designer|support specialist|"
    r"customer success|hr\b|accountant|content writer|seo)\b", re.I)
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to|–)?\s*(\d{1,2})?\s*\+?\s*(?:years|yrs)", re.I)


def required_years(description: str) -> int | None:
    """Smallest 'N years' requirement stated in the posting (None if unstated)."""
    mins = []
    for m in YEARS_RE.finditer(description[:6000]):
        lo = int(m.group(1))
        if 0 < lo <= 20:
            mins.append(lo)
    return min(mins) if mins else None


def seniority_ok(title: str, description: str, max_years: int) -> tuple[bool, str]:
    if NON_ENGINEERING_RE.search(title):
        return False, "not_engineering"
    if SENIOR_TITLE_RE.search(title):
        return False, "too_senior:title"
    years = required_years(description)
    if years is not None and years > max_years:
        return False, f"too_senior:{years}y_required"
    return True, "seniority_ok"


def annual_inr(amount: float | None, currency: str | None, cfg: dict) -> float | None:
    """Normalise a salary figure to INR/year. Monthly figures are scaled up."""
    if not amount:
        return None
    rate = cfg["salary"]["usd_to_inr"] if (currency or "").upper() == "USD" else 1.0
    value = float(amount) * rate
    if value < 200_000 and (currency or "").upper() != "USD":
        value *= 12  # INR figures under 2 L are monthly
    elif (currency or "").upper() == "USD" and float(amount) < 20_000:
        value *= 12  # USD figures under 20k are monthly
    return value


def salary_ok(job: dict, cfg: dict) -> tuple[bool, str]:
    floor = cfg["salary"]["min_inr_per_year"]
    top = annual_inr(job.get("salary_max") or job.get("salary_min"), job.get("currency"), cfg)
    if not floor or top is None:
        return True, "salary_unpublished" if top is None else "salary_ok"
    if top < floor:
        return False, f"salary_below_floor:{top/1e5:.1f}L"
    return True, "salary_ok"


def is_stale(date_posted: str | None, max_days: int) -> bool:
    if not date_posted:
        return False
    try:
        raw = str(date_posted)
        posted = (datetime.fromtimestamp(int(raw), tz=timezone.utc) if raw.isdigit()
                  else datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except (ValueError, OverflowError):
        return False  # unparseable date: keep the job rather than drop a live posting
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - posted > timedelta(days=max_days)


def passes_filters(job: dict, cfg: dict) -> tuple[bool, str]:
    search = cfg["search"]
    ok, loc_reason = is_location_eligible(job.get("location"), job.get("title"),
                                          job.get("description"), cfg)
    if not ok:
        return False, loc_reason
    if is_stale(job.get("date_posted"), search["max_job_age_days"]):
        return False, "stale_posting"
    ok, reason = seniority_ok(job.get("title") or "", job.get("description") or "",
                              search["max_required_years"])
    if not ok:
        return False, reason
    ok, reason = salary_ok(job, cfg)
    if not ok:
        return False, reason
    return True, loc_reason
