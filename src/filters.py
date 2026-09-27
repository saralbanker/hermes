"""
filters.py — Cheap deterministic job filters applied before any LLM call.

    passes_filters(job, cfg) -> (bool, reason)
    classify_tier(title, description, cfg) -> (tier | None, required_years | None, reason)
    role_priority(title, description) -> int

Checks, in order: location (geo.py), staleness, role exclusions, tier/seniority,
salary floor. Every rejection carries a reason string that is stored in
jobs.status_reason, so `tracker.py` can show why jobs were dropped.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from geo import is_location_eligible
from states import CORE, STRETCH

# ---------------------------------------------------------------------------
# Title / responsibility classification
# ---------------------------------------------------------------------------

# People-management titles → always filtered (owner: Manager/Director/VP/Head-of).
MANAGEMENT_TITLE_RE = re.compile(
    r"\b(engineering manager|eng\.? manager|director|vp\b|vice president|head of|"
    r"chief\b|cto\b|ceo\b|coo\b|people manager|team lead(?!er)?\b)\b", re.I)

# Senior/stretch signal titles (owner: NOT globally rejected — they define the
# stretch tier instead).
STRETCH_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|founding engineer|architect|"
    r"distinguished|sde[- ]?(iii|3)|l[5-9]\b|engineer (iii|iv|3|4))\b", re.I)

# Role exclusions (owner list): evaluated against title AND description.
EXCLUDE_ROLE_PATTERNS: dict[str, re.Pattern] = {
    "qa_only": re.compile(
        r"\b(qa engineer|quality assurance engineer|manual test(er|ing)|"
        r"test engineer|sdet)\b", re.I),
    "support": re.compile(
        r"\b(technical support|customer support|customer success|help ?desk|support specialist|"
        r"support engineer)\b", re.I),
    "recruiting": re.compile(r"\b(recruiter|recruiting|talent acquisition|sourcer)\b", re.I),
    "sales": re.compile(
        r"\b(sales|sdr\b|bdr\b|account executive|account manager|business development)\b", re.I),
    "marketing": re.compile(r"\b(marketing|seo\b|content writer|copywriter|social media)\b", re.I),
    "non_tech_ops": re.compile(
        r"\b(operations (associate|coordinator|specialist)|office manager|"
        r"data entry|virtual assistant)\b", re.I),
    "non_engineering_title": re.compile(
        r"\b(business analyst|data analyst|product manager|program manager|project manager|"
        r"product owner|scrum master|designer|consultant(?!.{0,20}(developer|engineer)))\b", re.I),
    "onboarding_only": re.compile(
        r"\b(implementation specialist|onboarding specialist|onboarding manager)\b", re.I),
    # Owner: no teaching roles. Title-only (never matched against a description), so a
    # real engineering posting that happens to say "mentor junior engineers" as a duty is
    # unaffected — see EXCLUDE_DUTY_PATTERNS below for that distinction. "Trainer"/"mentor"
    # alone are ambiguous ("ML model trainer" trains models, not people) so they only
    # count paired with a teaching/academy/student context; "teacher"/"tutor"/"instructor"
    # are unambiguous on their own (observed live: "Online Teachers/Tutors/Mentors for
    # Software Academy" and "AI Coding Trainer" both slipped through before this).
    "teaching": re.compile(
        r"\b(teachers?|tutors?|instructors?|educators?|professors?|lecturers?|faculty|teaching assistants?)\b|"
        r"\b(coding|software|programming|python|web development|tech|technical)\s+mentors?\b|"
        r"\bmentors?\b.{0,40}\b(academy|students?|bootcamp|curriculum)\b|"
        r"\bacademy\b.{0,40}\bmentors?\b|"
        r"\b(?<!model\s)(?<!models\s)\btrainers?\b",
        re.I),
}

# Description-level exclusions: only phrases that describe THE ROLE'S OWN duties.
# A bare word ("sales", "marketing", "support") in a company blurb — e.g. "AI for
# sales teams" — must not reject an engineering job.
EXCLUDE_DUTY_PATTERNS: dict[str, re.Pattern] = {
    "support": re.compile(
        r"\b(provide|providing|deliver|delivering)\s+(l[1-3]|level[- ][1-3]|first[- ]line|"
        r"second[- ]line|advanced|technical|production|application|end[- ]user)\s+support\b|"
        r"\b(resolve|handle|triage)\s+(customer|user|support)\s+(tickets|issues|queries)\b|"
        r"\b(l[1-3]|level[- ][1-3])\s+support\s+(role|position|engineer|analyst)\b", re.I),
    "qa_only": re.compile(
        r"\b(write|execute|executing|writing)\s+(manual\s+)?test\s+cases\b.{0,80}\bmanual\b|"
        r"\bthis is a (manual )?(qa|testing) role\b", re.I),
    "sales": re.compile(r"\b(meet|exceed|hit)\s+(sales\s+)?quota|\bcold (calling|outreach)\b", re.I),
}

# Phrases that mean the role is customer-facing but still genuinely engineering
# (owner: acceptable — must not be caught by the exclusions above).
ENGINEERING_ESCAPE_RE = re.compile(
    r"\b(forward[- ]deployed engineer|solutions engineer|solution architect(?:ing)?|"
    r"customer engineer|technical account manager.{0,40}\b(code|build|develop|engineer)\b)\b",
    re.I)

YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)|"
    r"(\d{1,2})\s*\+\s*(?:years?|yrs?)|"
    r"(\d{1,2})\s*(?:years?|yrs?)",
    re.I)
# Contexts that mention "N years" but are NOT an experience requirement —
# skip these matches (company age, product age, visa/notice periods, etc.).
NON_REQUIREMENT_CONTEXT_RE = re.compile(
    r"(founded|established|in business|around|incorporated|since)\s+(for\s+)?(over\s+)?$|"
    r"(visa|notice period|contract|lease|warranty)\D{0,15}$",
    re.I)


def role_priority(title: str, description: str) -> int:
    """
    Higher = more desirable per owner ranking:
      6 AI/LLM/ML-app > 5 backend > 4 full-stack > 3 general SWE >
      2 automation/platform/internal tools > 1 frontend-only
    """
    text = f"{title or ''} {(description or '')[:1500]}".lower()
    if re.search(r"\b(ai|artificial intelligence|llm|large language model|ml\b|"
                 r"machine learning|genai|gen ai|rag\b)\b", text):
        return 6
    if re.search(r"\bbackend\b|\bback-end\b|\bback end\b", text):
        return 5
    if re.search(r"\bfull[- ]?stack\b", text):
        return 4
    if re.search(r"\bautomation\b|\bplatform engineer\b|\binternal tools?\b|\bdevops\b|"
                 r"\bsre\b|\bsite reliability\b", text):
        return 2
    if re.search(r"\bfrontend\b|\bfront-end\b|\bfront end\b|\bui engineer\b", text):
        return 1
    return 3  # general software engineering


def required_years(description: str) -> int | None:
    """
    Smallest 'N years' EXPERIENCE requirement stated in the posting (None if
    unstated). "3-5 years" -> 3. "5+ years" -> 5. Ignores non-requirement
    contexts like "company founded 10 years ago" where reasonably detectable.
    """
    if not description:
        return None
    mins = []
    for m in YEARS_RE.finditer(description[:6000]):
        prefix = description[max(0, m.start() - 30):m.start()]
        if NON_REQUIREMENT_CONTEXT_RE.search(prefix):
            continue
        lo_range, _hi_range, plus, plain = m.group(1), m.group(2), m.group(3), m.group(4)
        lo = lo_range or plus or plain
        if lo is None:
            continue
        lo = int(lo)
        if 0 < lo <= 20:
            mins.append(lo)
    return min(mins) if mins else None


# Allow-list: the title itself must name engineering work (block-lists miss
# "Graphic Designer", "Founder's Office", "Content Creator Intern", …).
ENGINEERING_TITLE_RE = re.compile(
    r"\b(engineer(ing)?|developer|programmer|dev\b|sde|swe|architect|software|full[- ]?stack|"
    r"back[- ]?end|front[- ]?end|devops|sre\b|platform|ai\b|ml\b|llm|machine learning|"
    r"data scientist|founding|technical lead|tech lead|coder|web3?\b|mern|mean stack|python|"
    r"golang|node(\.?js)?|react|typescript|javascript|java\b|automation)", re.I)


def _exclusion_reason(title: str, description: str) -> str | None:
    text_title = title or ""
    text_desc = (description or "")[:3000]
    combined = f"{text_title} {text_desc}"
    if ENGINEERING_ESCAPE_RE.search(combined):
        return None  # explicitly acceptable customer-facing engineering
    for reason, pattern in EXCLUDE_ROLE_PATTERNS.items():
        if pattern.search(text_title):
            return reason
    for reason, pattern in EXCLUDE_DUTY_PATTERNS.items():
        if pattern.search(text_desc):
            return reason
    if not ENGINEERING_TITLE_RE.search(text_title):
        return "not_engineering_title"
    return None


def classify_tier(title: str, description: str, cfg: dict) -> tuple[str | None, int | None, str]:
    """
    Returns (tier, required_years, reason).
    tier is None when the job should be filtered out entirely; reason then
    explains why. required_years is the parsed value (may be None).
    """
    title = title or ""
    description = description or ""
    search = cfg["search"]

    excl = _exclusion_reason(title, description)
    if excl:
        return None, None, f"excluded_role:{excl}"

    if MANAGEMENT_TITLE_RE.search(title):
        return None, None, "excluded_role:people_management"

    years = required_years(description)
    is_stretch_title = bool(STRETCH_TITLE_RE.search(title))

    stretch_max = search.get("stretch_max_years", 8)
    core_max = search.get("core_max_years", 4)

    if years is not None and years > stretch_max:
        return None, years, f"too_senior:{years}y_required"

    if is_stretch_title or (years is not None and years > core_max):
        return STRETCH, years, "tier:stretch"

    return CORE, years, "tier:core"


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

def _normalize_period_amount(amount: float, period: str | None, text_hint: str = "",
                              currency: str = "") -> float:
    """Normalise an amount to a per-month figure given an explicit or heuristic period."""
    period = (period or "").lower().strip()
    if not period:
        hint = text_hint.lower()
        if re.search(r"\b(hour|hr|/hr|hourly)\b", hint):
            period = "hour"
        elif re.search(r"\b(year|yr|annum|annual|/yr|/year)\b", hint):
            period = "year"
        elif re.search(r"\b(month|/mo|monthly)\b", hint):
            period = "month"
        else:
            # Currency-specific fallback threshold: a bare number this small is
            # almost always a monthly figure, larger is almost always yearly.
            yearly_threshold = 20_000 if currency == "USD" else 200_000
            period = "year" if amount >= yearly_threshold else "month"
    if period.startswith("hour"):
        return amount * 160  # ~160 working hours/month
    if period.startswith("year") or period.startswith("annum") or period.startswith("annual"):
        return amount / 12
    return amount  # already monthly


def monthly_inr(job: dict, cfg: dict) -> float | None:
    """Normalise the job's published pay to INR/month. None if unpublished."""
    amount = job.get("salary_max") or job.get("salary_min")
    if not amount:
        return None
    currency = (job.get("currency") or "").upper()
    period = job.get("salary_period")
    text_hint = f"{job.get('title', '')} {(job.get('description') or '')[:500]}"
    monthly_native = _normalize_period_amount(float(amount), period, text_hint, currency)
    if currency == "USD":
        return monthly_native * cfg["salary"]["usd_to_inr"]
    return monthly_native


def salary_ok(job: dict, cfg: dict) -> tuple[bool, str]:
    is_india = (job.get("currency") or "").upper() != "USD"
    floor = (cfg["salary"]["min_inr_per_month_india"] if is_india
             else cfg["salary"]["min_inr_per_month_global"])
    monthly = monthly_inr(job, cfg)
    if monthly is None:
        return True, "salary_unpublished"
    if monthly < floor:
        return False, f"salary_below_floor:{monthly/1000:.0f}k/mo"
    return True, "salary_ok"


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def passes_filters(job: dict, cfg: dict) -> tuple[bool, str]:
    search = cfg["search"]
    ok, loc_reason = is_location_eligible(job.get("location"), job.get("title"),
                                          job.get("description"), cfg)
    if not ok:
        return False, loc_reason
    if is_stale(job.get("date_posted"), search["max_job_age_days"]):
        return False, "expired"

    tier, _years, reason = classify_tier(job.get("title") or "", job.get("description") or "", cfg)
    if tier is None:
        return False, reason

    ok, reason = salary_ok(job, cfg)
    if not ok:
        return False, reason
    return True, loc_reason
