"""Response classification — DATA_MODEL.md §11.3 (Patch 10), the five
authoritative categories, deterministic keyword/regex based (no LLM
required — same approach src/response_watcher.py already uses and proved
in production; this is a new pattern set for the new taxonomy, not a
duplicate of the old 4-category one, since the categories themselves
changed under Patch 10):

    screening_follow_up    -- resume/portfolio/GitHub request, project info
    human_required_signal  -- interview/salary/offer/contract/legal-document
    rejection
    acknowledgement
    ambiguous               -- correlated, but none of the above matched

Only called on a message that already correlated to a real opportunity/
attempt (src/engine/gmail/correlate.py) — an uncorrelated message is never
classified into one of these five; see pipeline.py.
"""

from __future__ import annotations

import re

SCREENING_FOLLOW_UP = "screening_follow_up"
HUMAN_REQUIRED_SIGNAL = "human_required_signal"
REJECTION = "rejection"
ACKNOWLEDGEMENT = "acknowledgement"
AMBIGUOUS = "ambiguous"

ALL_CATEGORIES = frozenset({
    SCREENING_FOLLOW_UP, HUMAN_REQUIRED_SIGNAL, REJECTION, ACKNOWLEDGEMENT, AMBIGUOUS,
})

# Rejection — checked first so a rejection that happens to mention
# "interview" in passing ("we won't be moving forward after the interview")
# is never misread as a human-required signal.
_REJECTION_PATTERNS = [
    r"\bunfortunately\b",
    r"not\s+(?:be\s+)?moving forward",
    r"other candidates",
    r"will not be (?:moving|proceeding)",
    r"decided not to (?:proceed|move forward)",
    r"not\s+(?:been\s+)?selected",
    r"position (?:has been|was) filled",
    r"pursue other candidates",
    r"regret to inform",
    r"we (?:have )?chosen to move forward with other",
]

# human_required_signal — AI_SYSTEM.md §28's forbidden-automation list:
# interview / salary / offer / contract / legal-identity-document. This is
# everything the automation boundary forbids Hermes from acting on itself.
_HUMAN_REQUIRED_PATTERNS = [
    r"schedule\s+(?:a|an|your)\s+(?:call|interview|chat)",
    r"invite you (?:to|for) (?:an?\s+)?interview",
    r"interview invitation",
    r"next round",
    r"move (?:you )?forward (?:with|to) (?:the )?next",
    r"calendly\.com",
    r"book a (?:time|slot|call)",
    r"select a time",
    r"(?:share|provide) your availability",
    r"your availability (?:for|to)",
    r"available for a (?:call|chat|interview)",
    r"shortlisted",
    r"take[- ]?home (?:assignment|test|challenge|project)",
    r"coding (?:test|challenge|assessment)",
    r"technical assessment",
    r"online assessment",
    r"\bhackerrank\b",
    r"\bcodility\b",
    r"complete (?:the|this) assessment",
    r"assessment (?:link|invite|invitation)",
    r"phone screen",
    r"next steps? in (?:the|your) (?:hiring|interview) process",
    # salary/offer/contract/legal — not covered by the legacy "positive" list at all
    r"(?:salary|compensation) (?:expectation|discussion|range|negotiation)",
    r"\boffer letter\b",
    r"pleased to offer",
    r"extend(?:ing)? an offer",
    r"\bcontract\b",
    r"background check",
    r"\bI-?9\b",
    r"proof of (?:identity|employment eligibility)",
    r"(?:w-?2|w-?9) form",
    r"employment agreement",
]

# screening_follow_up — a repeatable, lower-stakes request, genuinely
# distinct from an interview/offer signal: asking for more material, not
# asking the candidate to make or receive a high-impact decision.
_SCREENING_FOLLOW_UP_PATTERNS = [
    r"(?:send|share|provide) (?:us )?(?:your |a )?(?:updated )?resume",
    r"(?:send|share|provide) (?:us )?(?:your |a )?portfolio",
    r"(?:send|share|provide) (?:us )?(?:your )?github",
    r"link to your (?:portfolio|github|work|projects?)",
    r"(?:more|additional) (?:information|details) (?:about|on) your (?:project|experience)",
    r"tell us more about",
    r"could you (?:elaborate|expand) on",
]

# Generic automated acknowledgement — never a human-required signal even if
# it mentions "interview" only conditionally ("if selected for interview...").
_ACKNOWLEDGEMENT_PATTERNS = [
    r"thank you for applying",
    r"thanks for applying",
    r"thank you for your application",
    r"thanks for your application",
    r"we(?:'ve| have)? received your application",
    r"application (?:has been |was )?received",
    r"application (?:has been |was )?submitted",
    r"your application to .* was submitted",
    r"your application has been sent",
    r"we will review your application",
    r"confirming receipt of your application",
    r"we have received your submission",
    r"received your resume",
    r"indeed application:",
]


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify(subject: str, body: str) -> str:
    """Returns one of the five DATA_MODEL.md §11.3 categories. Call only on
    an already-correlated message (§11.4) — this function has no "noise"
    escape hatch; an uncorrelated message should never reach it (see
    pipeline.py)."""
    text = f"{subject or ''}\n{body or ''}".lower()
    if _matches_any(_REJECTION_PATTERNS, text):
        return REJECTION
    if _matches_any(_HUMAN_REQUIRED_PATTERNS, text):
        return HUMAN_REQUIRED_SIGNAL
    if _matches_any(_SCREENING_FOLLOW_UP_PATTERNS, text):
        return SCREENING_FOLLOW_UP
    if _matches_any(_ACKNOWLEDGEMENT_PATTERNS, text):
        return ACKNOWLEDGEMENT
    return AMBIGUOUS
