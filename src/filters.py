"""
filters.py — Cheap deterministic job filters applied before any LLM call.

    passes_filters(job, cfg) -> (bool, reason)
    classify_tier(title, description, cfg) -> (tier | None, required_years | None, reason)
    assess(title, description, cfg) -> Qualification   (policy gates + evidence engine)
    role_priority(title, description) -> int

Checks, in order: location (geo.py), staleness, role exclusions, qualification (qualify.py:
stack/seniority/years/constraint evidence), salary floor. Every rejection carries a reason string that is stored in
jobs.status_reason, so `tracker.py` can show why jobs were dropped.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from geo import is_location_eligible
from qualify import REJECTED, REVIEW, Qualification, Signal, qualify, to_columns

REVIEW_REASON_PREFIX = "qualification_review:"

# ---------------------------------------------------------------------------
# Title / responsibility classification
# ---------------------------------------------------------------------------

# People-management titles → always filtered (owner: Manager/Director/VP/Head-of).
MANAGEMENT_TITLE_RE = re.compile(
    r"\b(engineering manager|eng\.? manager|manager\s*(?:,|-|–|—|:|/|of)\s*(?:software\s+)?engineering|director|vp\b|vice president|head of|"
    r"chief\b|cto\b|ceo\b|coo\b|people manager|team lead(?!er)?\b)\b", re.I)

# A standalone "Manager" title noun (title end, after a dash/comma, or before a comma / "of"):
# "Sr. Engagement Manager, Forward Deployed Engineering", "Services - Manager". Not "Package Manager
# Engineer". Product/Project/Program Manager are caught earlier by non_engineering_title.
STANDALONE_MANAGER_RE = re.compile(r"[-–—,]\s*manager\b|\bmanager\s*(?:,|of\b|$)", re.I)

# Role exclusions (owner list): evaluated against title AND description.
EXCLUDE_ROLE_PATTERNS: dict[str, re.Pattern] = {
    "qa_only": re.compile(
        r"\b(qa engineer|quality assurance engineer|manual test(er|ing)|"
        r"test engineer|engineers? in test|sdet|qa)\b", re.I),
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
    return None


def _is_people_management(title: str, description: str) -> bool:
    if MANAGEMENT_TITLE_RE.search(title):
        return True
    is_customer_facing_engineering = bool(ENGINEERING_ESCAPE_RE.search(f"{title} {description[:3000]}"))
    return bool(STANDALONE_MANAGER_RE.search(title.strip())) and not is_customer_facing_engineering


def assess(title: str, description: str, cfg: dict) -> Qualification:
    """Policy gates (owner role exclusions, people management), then the evidence engine."""
    title, description = title or "", description or ""
    policy = _exclusion_reason(title, description)
    if policy is None and _is_people_management(title, description):
        policy = "people_management"
    if policy:
        signal = Signal("title", "role", -1, 1.0, f"policy:{policy}", True)
        return Qualification(REJECTED, None, 1.0, 0.0, None, (f"policy:{policy}",), (signal,))
    return qualify(title, description, cfg)


def classify_tier(title: str, description: str, cfg: dict) -> tuple[str | None, int | None, str]:
    """
    Returns (tier, required_years, reason). tier is None when the job is rejected. A `review`
    decision keeps its tier but carries a "qualification_review:" reason (never auto-applied).
    """
    qual = assess(title, description, cfg)
    top = qual.reasons[0]
    if qual.decision == REJECTED:
        if top.startswith("policy:"):
            return None, None, f"excluded_role:{top.removeprefix('policy:')}"
        return None, qual.required_years, f"qualification:{top}"
    if qual.decision == REVIEW:
        return qual.tier, qual.required_years, f"{REVIEW_REASON_PREFIX}{top}"
    return qual.tier, qual.required_years, f"tier:{qual.tier}"


def qualification_fields(title: str, description: str, cfg: dict) -> dict[str, object]:
    """jobs.qual_* column values for this posting (written at discovery / backlog rescoring)."""
    return to_columns(assess(title, description, cfg))


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

    tier, _years, tier_reason = classify_tier(job.get("title") or "", job.get("description") or "", cfg)
    if tier is None:
        return False, tier_reason

    ok, reason = salary_ok(job, cfg)
    if not ok:
        return False, reason
    if tier_reason.startswith(REVIEW_REASON_PREFIX):
        return False, tier_reason  # fail closed: a human releases it (scripts/release_manual_review.py)
    return True, loc_reason
