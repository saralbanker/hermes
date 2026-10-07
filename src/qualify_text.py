"""
qualify_text.py — Text-evidence primitives for the qualification engine (src/qualify.py).

    normalize_text(text)            -> markdown-stripped text
    split_sections(text)            -> (lines tagged required/preferred/other, has_headers)
    build_profile(cfg)              -> Profile (compiled candidate-stack matchers, from config.yaml)
    find_years(lines, text, ...)    -> YearsFinding (overall experience requirement actually used)

Pure functions, no I/O. Everything candidate-specific comes from `cfg["qualification"]`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

REQUIRED, PREFERRED, OTHER = "required", "preferred", "other"

# ---------------------------------------------------------------------------
# Normalisation and section splitting
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Strip markdown escapes/emphasis ("11\\+ years", "**Role**") so regexes see plain text."""
    text = (text or "").replace("\\", "")
    return re.sub(r"[*_`]{1,3}", "", text)


_LEAD_WORDS = r"(?:(?:the|your|our|key|minimum|basic|technical|core|essential|mandatory|required)\s+)*"
_REQ_MARKERS = (
    r"requirements?|must[- ]haves?|what you(?:'|’)?ll need|what you need|you have|you bring|"
    r"you(?:'|’)?ve got|qualifications?|who you are|skills? required|what we(?:'|’)?re looking for|"
    r"what we are looking for|your profile|about you|key skills|ideal candidate|required skills|"
    r"(?:min(?:imum)?\.?\s+)?experience(?:\s+required)?")
_PREF_MARKERS = (
    r"nice[- ]to[- ]haves?|preferred(?: qualifications| skills)?|bonus(?: points)?|good to have|"
    r"ideally|plus(?:es)?|extra credit|desirable")
_OTHER_MARKERS = (
    r"about (?:us|the (?:company|role|team|job))|responsibilities|what you(?:'|’)?ll do|"
    r"what you will do|the role|benefits|perks|what we offer|why join|job description|overview|"
    r"compensation|how to apply|the opportunity|day[- ]to[- ]day")
_HEADER_RE = re.compile(
    rf"^\W*{_LEAD_WORDS}(?:(?P<req>{_REQ_MARKERS})|(?P<pref>{_PREF_MARKERS})|(?P<other>{_OTHER_MARKERS}))\b"
    r"(?P<rest>.*)$", re.I)
# Markers that usually begin a sentence ("You have 3 years of Python") — header only with a colon.
_SENTENCE_MARKER_RE = re.compile(
    r"^\W*(?:you have|you bring|you(?:'|’)?ve got|about you|(?:min(?:imum)?\.?\s+)?experience)\b", re.I)
_BULLET_RE = re.compile(r"^\s*(?:[-•·▪◦*]|\d+[.)])\s+")
_PREFERRED_CUE_RE = re.compile(
    r"\b(preferred|nice to have|(?:a|major|big)?\s*plus|bonus|ideally|advantage|desirable|good to have|"
    r"would be (?:great|nice)|not required)\b", re.I)
# Long asides only: a bare "(Preferred)" tag (Indeed's "Python: 5 years (Preferred)") must still count.
_PARENTHETICAL_RE = re.compile(r"\([^()]{20,}\)")


@dataclass(frozen=True)
class Signal:
    """One piece of evidence. polarity -1 = mismatch, +1 = fit; strength 0..1."""
    source: str      # title | desc_required | desc_preferred | desc_other | years | desc_duties
    dimension: str   # stack | seniority | constraint | role | fit
    polarity: int
    strength: float
    detail: str
    is_decisive: bool = False


@dataclass(frozen=True)
class Line:
    text: str
    section: str  # REQUIRED | PREFERRED | OTHER


def _header_match(raw: str) -> tuple[str, str] | None:
    """(section, inline_content) when `raw` is a section header line, else None."""
    if _BULLET_RE.match(raw):
        return None
    text = raw.strip().lstrip("#").strip()
    match = _HEADER_RE.match(text)
    if not match or len(text) > 90:
        return None
    section = REQUIRED if match.group("req") else PREFERRED if match.group("pref") else OTHER
    rest = match.group("rest").strip()
    inline = re.match(r"^[:\-–—]\s*(\S.*)$", rest)
    if inline:
        # "Min Experience: 4+ years" — keep the key so the figure reads as the OVERALL requirement
        keep_key = "experience" in match.group(0).lower()
        return section, text if keep_key else inline.group(1)
    if not rest or rest == ":" or (rest.endswith(":") and len(text) <= 60):
        return section, ""
    is_sentence_start = bool(_SENTENCE_MARKER_RE.match(text))
    is_short_label = len(rest) <= 25 and not re.search(r"[\d.!?,]", rest)
    return (section, "") if is_short_label and not is_sentence_start else None


def split_sections(text: str) -> tuple[list[Line], bool]:
    """Tag each description line required/preferred/other. With no recognisable headers the
    whole description is OTHER (weaker evidence) — never REQUIRED."""
    lines: list[Line] = []
    section, has_headers = OTHER, False
    for raw in text.splitlines():
        if not raw.strip():
            continue
        header = _header_match(raw)
        content = raw.strip()
        if header:
            section, content = header[0], header[1]
            has_headers = True
            if not content:
                continue
        # A cue inside parentheses qualifies only that aside ("5+ yrs Python (VSCode a plus)").
        unparenthesized = _PARENTHETICAL_RE.sub(" ", content)
        tagged = PREFERRED if _PREFERRED_CUE_RE.search(unparenthesized) else section
        lines.append(Line(content, tagged))
    return lines, has_headers


# ---------------------------------------------------------------------------
# Candidate profile (from config.yaml `qualification:`)
# ---------------------------------------------------------------------------

_NO_MATCH = re.compile(r"(?!x)x")


@lru_cache(maxsize=64)
def _token_regex(tokens: tuple[str, ...]) -> re.Pattern[str]:
    """Word-bounded alternation. 'java' never matches 'JavaScript'; 'c#'/'c++'/'.net' work.
    A token followed by Capital/Ventures/Partners/Labs/Fund is a company name ("Spark Capital")."""
    parts = sorted((re.escape(t.lower()).replace(r"\ ", r"[\s-]+") for t in tokens if t),
                   key=len, reverse=True)
    if not parts:
        return _NO_MATCH
    return re.compile(r"(?<!\w)(" + "|".join(parts) + r")s?(?![\w#+])(?!\s+(?:capital|ventures|partners|labs|fund)\b)", re.I)


@dataclass(frozen=True)
class Profile:
    core: re.Pattern[str]
    title_core: re.Pattern[str]  # core tokens plus title-only ones ("Go" is too common in prose)
    core_distinctive: re.Pattern[str]  # core minus generic tokens (SQL, Docker, REST ...)
    academic: re.Pattern[str]
    absent: re.Pattern[str]
    platform: re.Pattern[str]
    ml_training: re.Pattern[str]
    llm_app: re.Pattern[str]
    junior_title: re.Pattern[str]
    ml_title: re.Pattern[str]       # ML-training role tokens, matched in titles only
    role_identity: re.Pattern[str]  # role-type tokens (DevOps, SRE, Data Engineer ...)
    any_tech: re.Pattern[str]
    languages: frozenset[str]
    has_bachelor: bool
    core_max_years: int
    stretch_max_years: int
    knockout_years: int


def build_profile(cfg: dict) -> Profile:
    qual = cfg["qualification"]
    search = cfg["search"]

    def rx(key: str) -> re.Pattern[str]:
        return _token_regex(tuple(qual.get(key, ())))

    all_tech = tuple(t for key in ("core_stack", "academic_stack", "absent_stack", "platform_tokens",
                                    "ml_training_tokens") for t in qual.get(key, ()))
    generic = {t.lower() for t in qual.get("generic_stack", ())}
    distinctive = tuple(t for t in qual.get("core_stack", ()) if t.lower() not in generic)
    return Profile(
        core=rx("core_stack"),
        title_core=_token_regex(tuple(qual.get("core_stack", ())) + tuple(qual.get("title_core_tokens", ()))),
        core_distinctive=_token_regex(distinctive), academic=rx("academic_stack"), absent=rx("absent_stack"),
        platform=rx("platform_tokens"), ml_training=rx("ml_training_tokens"),
        llm_app=rx("llm_app_tokens"), junior_title=rx("junior_title_tokens"), role_identity=rx("role_identity_tokens"), ml_title=rx("ml_training_title_tokens"),
        any_tech=_token_regex(all_tech),
        languages=frozenset(lang.lower() for lang in qual.get("languages", ())),
        has_bachelor=bool(qual.get("has_bachelor", False)),
        core_max_years=search.get("core_max_years", 2),
        stretch_max_years=search.get("stretch_max_years", 4),
        knockout_years=qual.get("knockout_years", 5),
    )


# ---------------------------------------------------------------------------
# Years extraction
# ---------------------------------------------------------------------------

YEARS_RE = re.compile(
    r"(\d{1,2})\s*(?:-|to|–)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)|"
    r"(\d{1,2})\s*\+\s*(?:years?|yrs?)|"
    r"(\d{1,2})\s*(?:years?|yrs?)",
    re.I)
# Contexts that mention "N years" but are NOT an experience requirement (company age, notice
# periods, ...).
NON_REQUIREMENT_CONTEXT_RE = re.compile(
    r"(founded|established|in business|around|incorporated|since)\s+(for\s+)?(over\s+)?$|"
    r"(visa|notice period|contract|lease|warranty)\D{0,15}$",
    re.I)
_FILLER_RE = re.compile(
    r"^\W*(?:(?:of|in|with|using|on|as|a|an|the|relevant|professional|hands[- ]on|strong|proven|"
    r"solid|commercial|practical|working|work|industry|real[- ]world|experience|exp)\b\W*)+", re.I)
_HEAD_EXPERIENCE_RE = re.compile(r"\b(?:experience|exp)\b[^.]{0,20}$", re.I)
_TAIL_EXPERIENCE_RE = re.compile(r"\b(?:experience|exp)\b", re.I)
_TAIL_DOMAIN_RE = re.compile(
    r"^\W*(?:in\s+|of\s+)?(?:software|web|application|engineering|development|backend|back-end|"
    r"frontend|front-end|full[- ]?stack|programming|coding|the industry)", re.I)
_MINIMUM_CUE_RE = re.compile(r"\b(?:minimum|min\.?|at least)\W{0,3}$", re.I)


# An OTHER-section line only counts as an experience requirement when it is phrased like one;
# "we have 15 years of experience delivering software" is a company blurb, not a requirement.
_REQUIREMENT_CUE_RE = re.compile(
    r"\b(?:requires?|required|must|minimum|at least|should have|needed?|you(?:'|’)?ll have|"
    r"you have|you bring|looking for|seeking|candidate|ideal|expected)\b|"
    r"^\W*(?:total |overall |minimum |required )?experience\b[^.]{0,15}\d", re.I)
_COMPANY_CUE_RE = re.compile(r"\b(?:we have|we(?:'|’)?ve|our (?:team|company|firm)|the company|has been)\b", re.I)


def is_requirement_line(line: "Line") -> bool:
    if line.section == REQUIRED:
        return True
    return bool(_REQUIREMENT_CUE_RE.search(line.text)) and not _COMPANY_CUE_RE.search(line.text)


@dataclass(frozen=True)
class YearsFinding:
    value: int | None
    kind: str          # "overall" | "per_skill" | "fallback" | "none"
    has_minimum_cue: bool = False


def _classify_years(line: str, match: re.Match[str], prof: Profile) -> str:
    """'overall' (experience in general) vs 'per_skill' ("2+ years of React")."""
    tail = line[match.end():match.end() + 60]
    head = line[max(0, match.start() - 40):match.start()]
    rest = _FILLER_RE.sub("", tail)
    if prof.any_tech.match(rest):
        return "per_skill"
    if _HEAD_EXPERIENCE_RE.search(head) or _TAIL_EXPERIENCE_RE.search(tail[:40]) \
            or _TAIL_DOMAIN_RE.match(tail):
        return "overall"
    return "per_skill"


def years_matches(line: str, prof: Profile) -> list[tuple[int, str, bool]]:
    found = []
    for m in YEARS_RE.finditer(line):
        if NON_REQUIREMENT_CONTEXT_RE.search(line[max(0, m.start() - 30):m.start()]):
            continue
        low = int(m.group(1) or m.group(3) or m.group(4))
        if 0 < low <= 20:
            has_min = bool(_MINIMUM_CUE_RE.search(line[max(0, m.start() - 15):m.start()]))
            found.append((low, _classify_years(line, m, prof), has_min))
    return found


def _fallback_years(lines: list[Line]) -> int | None:
    """Legacy behaviour: smallest 'N years' anywhere outside preferred lines (low confidence)."""
    values = [low for line in lines if line.section != PREFERRED and not _COMPANY_CUE_RE.search(line.text)
              for m in YEARS_RE.finditer(line.text)
              if not NON_REQUIREMENT_CONTEXT_RE.search(line.text[max(0, m.start() - 30):m.start()])
              for low in [int(m.group(1) or m.group(3) or m.group(4))] if 0 < low <= 20]
    return min(values) if values else None


def find_years(lines: list[Line], prof: Profile) -> YearsFinding:
    """Overall experience requirement from non-preferred lines; else the largest per-skill
    figure; else the legacy smallest-number fallback (low confidence)."""
    overall: list[tuple[int, bool]] = []
    per_skill: list[tuple[int, bool]] = []
    for line in lines:
        if line.section == PREFERRED or not is_requirement_line(line):
            continue
        for value, kind, has_min in years_matches(line.text, prof):
            (overall if kind == "overall" else per_skill).append((value, has_min))
    for kind, found in (("overall", overall), ("per_skill", per_skill)):
        if found:
            value = max(v for v, _ in found)
            return YearsFinding(value, kind, any(m for v, m in found if v == value))
    fallback = _fallback_years(lines)
    return YearsFinding(fallback, "fallback" if fallback is not None else "none")
