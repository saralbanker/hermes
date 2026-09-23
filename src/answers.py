"""
answers.py — Truthful answers to application-form screening questions.

Shared by every apply channel (Indeed, Greenhouse, Lever, Ashby).

    answer_question(label, options=None, kind="text") -> str | None

Order of resolution:
  1. Deterministic rules keyed on the question label (fast, consistent).
  2. For choice questions: pick the option matching the rule answer.
  3. Free text: local LLM grounded ONLY in profile/facts.md.
Returns None when no truthful answer exists — callers must leave the field
empty (optional field) or abort the application (required field).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from llm import LLMUnavailable, chat, facts

ROOT = Path(__file__).parent.parent


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return yaml.safe_load(open(ROOT / "config.yaml"))


def _profile() -> dict:
    return _cfg()["profile"]


def _screening() -> dict:
    return _cfg()["screening_answers"]


_JOB_CONTEXT = ""
_JOB_LOCATION = ""


def _abroad(text: str) -> bool:
    """True when the question or the job location points to a country other than India —
    the candidate is authorized only in India and would need sponsorship elsewhere."""
    from geo import RESTRICTED_RE
    question, _, location = text.partition("\x00")
    for part in (question, location):  # a country named in the question wins over the location
        if re.search(r"\bindia\b", part, re.I):
            return False
        if RESTRICTED_RE.search(part):
            return True
    return False


def _rules(label_ctx: str = "") -> list[tuple[str, str]]:
    """(regex on lowercased label, answer). First match wins — order matters.
    label_ctx = question + job location, for the country-dependent answers."""
    p, s = _profile(), _screening()
    first, *_, last = p["name"].split()
    return [
        (r"first name|given name", first),
        (r"last name|surname|family name", last),
        (r"full name|^name\b|your name", p["name"]),
        (r"e-?mail", p["email"]),
        (r"phone|mobile|contact number", p["phone"]),
        (r"linkedin", p.get("linkedin", "")),
        (r"github", "https://" + p["github"]),
        (r"portfolio|website|personal site|other url", "https://" + p["portfolio"]),
        (r"sponsor", "Yes" if _abroad(label_ctx) else "No"),
        (r"legally (authorized|allowed)|authori[sz](ed|ation) to work|right to work|work permit",
         "No" if _abroad(label_ctx) else s["work_authorization_short"]),
        (r"relocat", "No"),
        (r"notice period|when can you start|start date|earliest start|availability",
         s["notice_period"]),
        (r"current(ly)? (employed|working)|are you employed", s["currently_employed"]),
        (r"expected (salary|ctc|compensation)|salary expectation|desired (salary|pay)|expected pay",
         s["salary_expectation"]),
        (r"current (salary|ctc|compensation)", s["current_ctc"]),
        (r"years? of (professional )?experience|how many years|total experience",
         str(s["years_experience_total"])),  # numeric → paid years; text kinds handled in answer_question
        (r"\bbachelor|\bb\.?tech\b|\bb\.?e\.?\b(?! (able|available|willing|comfortable))|\bmaster'?s\b|computer science degree", "No"),
        (r"highest (level of )?education|degree|qualification", s["degree"]),
        (r"(\bcity\b|\blocation\b|where are you (located|based)|current location)", p["location"]),
        (r"country", "India"),
        (r"time ?zone", "IST (UTC+5:30); comfortable overlapping with EU and US-East mornings"),
        (r"remote", "Yes"),
        (r"gender|race|ethnic|veteran|disabilit|pronoun", "Decline to self-identify"),
        (r"(how|where) did you (first )?(hear|find|learn|come across)|^source\b|referr", "Job board"),
        (r"background check|drug (test|screen)", "Yes"),
        (r"(18|eighteen) years|of legal age|over the age", "Yes"),
        (r"privacy|consent|agree|acknowledge|terms", "Yes"),
        (r"use (of )?ai|ai (tools|assist)", s["ai_usage_statement"]),
    ]


YEARS_RE = re.compile(r"years? of (professional )?experience|how many years|total experience")


SKILL_YEARS_RE = re.compile(
    r"years?\s+of\s+([\w .+#/-]{2,40}?)\s+(?:experience|exp)\b|"
    r"(?:experience|exp)\s+(?:do you have\s+|have you had\s+)?(?:with|in|using|on)\s+([\w .+#/-]{2,40}?)(?:\?|$|\s+do\b|\s+have\b)")
GENERIC_EXPERIENCE = re.compile(
    r"^(professional|work|working|total|relevant|overall|industry|software|development|"
    r"software development|engineering|related|full[- ]time|paid|hands[- ]on)$")


def skill_years_answer(label: str) -> str | None:
    """Years with a NAMED technology/domain. '0' unless the fact sheet lists it.

    Never answers the generic figure for a specific skill: 'years of Amazon Connect
    experience' must be 0 for a candidate who has never used Amazon Connect.
    """
    m = SKILL_YEARS_RE.search(label.lower())
    if not m:
        return None
    skill = (m.group(1) or m.group(2) or "").strip(" ?.")
    skill = re.sub(r"^(hands[- ]on|professional|relevant|working|practical)\s+", "", skill)
    if not skill or GENERIC_EXPERIENCE.match(skill):
        return None
    # Only what the candidate HAS: the fact sheet's "does NOT have" list names AWS, Kubernetes…
    known = facts().lower().split("## things the candidate does not have")[0]
    known = re.sub(r"[\w.+#-]+\s*\(academic[^)]*\)", " ", known)  # coursework ≠ paid years
    words = [w for w in re.split(r"[\s/]+", skill) if len(w) > 1]
    has_skill = bool(words) and all(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", known) for w in words)
    return str(_screening()["years_experience_total"]) if has_skill else "0"


def rule_answer(label: str) -> str | None:
    text = label.lower().strip()
    specific = skill_years_answer(text)
    if specific is not None:
        return specific
    for pattern, answer in _rules(f"{text}\x00{_JOB_LOCATION}"):
        if re.search(pattern, text):
            return answer or None
    return None


def _pick_option(answer: str, options: list[str]) -> str | None:
    """Map a free-form answer onto one of the form's options."""
    a = answer.lower().strip()
    norm = {o: o.lower().strip() for o in options}
    for o, n in norm.items():
        if n == a:
            return o
    for o, n in norm.items():
        if a.startswith(n) or n.startswith(a):
            return o
    if a in ("no", "yes"):
        for o, n in norm.items():
            if n.split()[0].strip(",.") == a:
                return o
    # Numeric experience: pick the bucket containing the number ("1-2 years", "0-1").
    if a.isdigit():
        years = int(a)
        for o, n in norm.items():
            nums = [int(x) for x in re.findall(r"\d+", n)]
            if len(nums) == 2 and nums[0] <= years <= nums[1]:
                return o
            if len(nums) == 1 and ("+" in n or "more" in n) and years >= nums[0]:
                return o
            if len(nums) == 1 and ("less" in n or "under" in n) and years < nums[0]:
                return o
    return None


def set_job_context(company: str, title: str, description: str, location: str = "") -> None:
    """The posting being applied to, so motivation questions ("why us?") can be answered
    from the employer's own description. Facts about the CANDIDATE still come only from
    the fact sheet."""
    global _JOB_CONTEXT, _JOB_LOCATION
    _JOB_LOCATION = location or ""
    _JOB_CONTEXT = f"Company: {company}\nRole: {title}\nPosting excerpt: {(description or '')[:1500]}"


SOURCE_FALLBACKS = ("job board", "indeed", "online job", "internet", "website", "other")


def llm_answer(question: str, options: list[str] | None = None, max_words: int = 90) -> str | None:
    """Grounded free-text answer. Returns None if the facts cannot support one."""
    choice = f"\nChoose EXACTLY one of these options and output it verbatim: {options}" if options else ""
    system = (
        "You answer job-application questions on behalf of the candidate, in first person.\n"
        "Use ONLY facts from the FACT SHEET. Never invent employers, numbers, degrees, "
        "certifications, domains, or years of experience. If the facts do not support an honest "
        "answer, output exactly: UNKNOWN\n"
        f"Plain text, professional, maximum {max_words} words."
    )
    job = (f"\n\nJOB POSTING (facts about the employer only — never about the candidate):\n"
           f"{_JOB_CONTEXT}") if _JOB_CONTEXT else ""
    prompt = f"FACT SHEET:\n{facts()}{job}\n\nQUESTION: {question}{choice}\n\nANSWER:"
    try:
        out = chat(prompt, system=system, temperature=0.2, max_tokens=220).strip().strip('"')
    except LLMUnavailable:
        return None
    if not out or "UNKNOWN" in out.upper():
        return None
    if options:
        return _pick_option(out, options)
    return out


def answer_question(label: str, options: list[str] | None = None, kind: str = "text") -> str | None:
    """
    kind: "text" | "textarea" | "choice" | "boolean".
    Returns the value to enter/select, or None if no truthful answer is known.
    """
    base = rule_answer(label)
    if options:
        if base:
            picked = _pick_option(base, options)
            if picked:
                return picked
            if base == "Job board":  # map onto whatever the form calls it
                for want in SOURCE_FALLBACKS:
                    hit = next((o for o in options if want in o.lower()), None)
                    if hit:
                        return hit
        return llm_answer(label, options)
    if kind == "boolean":
        return base if base in ("Yes", "No") else llm_answer(label, ["Yes", "No"])
    if base and kind == "textarea" and YEARS_RE.search(label.lower()):
        return _screening()["years_experience_text"]  # prose answer: state both honest figures
    if base:
        return base
    return llm_answer(label, max_words=150 if kind == "textarea" else 40)
