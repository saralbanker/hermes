"""
qualify_constraints.py — Constraint and non-job evidence for the qualification engine.

    constraint_signals(title, text, lines, prof) -> list[Signal]

Decisive signals (explicit, near-certain knockouts): required non-English language, a posting
written mostly in another language, security clearance / citizenship, talent-pool or
fellowship/paid-training postings, postdoc / PhD required, student-only internships.
Weak signals: degree requirement, mandatory certification (strong but non-decisive).
"""
from __future__ import annotations

import re

from qualify_text import PREFERRED, REQUIRED, Line, Profile, Signal

_LANGUAGES: dict[str, str] = {
    "german": r"german|deutsch\w*", "french": r"french|fran[cç]ais\w*", "spanish": r"spanish|espa[nñ]ol|castellano",
    "dutch": r"dutch|nederlands\w*", "portuguese": r"portuguese|portugu[eê]s", "italian": r"italian|italiano",
    "japanese": r"japanese", "mandarin": r"mandarin|chinese", "korean": r"korean", "arabic": r"arabic",
    "russian": r"russian", "polish": r"polish", "swedish": r"swedish", "turkish": r"turkish",
}
_FLUENCY = (r"(?:fluent|fluency|native|business[- ]level|proficien\w+|professional|excellent|strong|good|"
            r"advanced|flie(?:ß|ss)end|verhandlungssicher|muttersprach\w+|courant|bilingual|"
            r"(?:very )?good command)")
_PREFERRED_CLAUSE_RE = re.compile(
    r"\b(?:plus|nice to have|advantage|bonus|preferred|desirable|ideally|beneficial|good to have)\b", re.I)
_TITLE_NON_ENGLISH_RE = re.compile(
    r"\b(entwickler(?:in)?|softwareentwickler|ingenieur|ing[ée]nieur|d[ée]veloppeur|desarrollador(?:a)?|"
    r"ontwikkelaar|programador(?:a)?|desenvolvedor(?:a)?|sviluppatore|programmierer)\b", re.I)

_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and of to in for with you we is are our will your on as or be that this".split()),
    "de": frozenset("und der die das mit für wir sie ist von zu den ein eine auf bei oder im sich als auch nicht".split()),
    "fr": frozenset("et le la les des du pour avec vous nous est une un dans sur que au aux ou".split()),
    "es": frozenset("el los las del para con una por que se es nuestro nuestra experiencia trabajo y".split()),
    "nl": frozenset("het een van voor met wij je op te bij ook zijn".split()),
    "pt": frozenset("os as do da para com uma que na no você nós em ao é".split()),
}
_MIN_WORDS_FOR_LANGUAGE_ID = 30

_TALENT_POOL_TITLE_RE = re.compile(
    r"\b(?:future (?:opportunities|openings|roles)|talent (?:pool|community|network)|general application|"
    r"open application|expression of interest)\b", re.I)
# Posting-level phrasing only: a passing "may be considered for future opportunities" never fires.
_TALENT_POOL_BODY_RE = re.compile(
    r"\bnot (?:an? )?(?:open|specific|current) (?:role|position|opening|vacancy)\b|"
    r"\bno (?:current|open) (?:openings?|vacanc(?:y|ies)|positions?)\b|"
    r"\bjoin our talent (?:community|pool|network)\b|"
    r"\bsubmit your (?:profile|resume|cv) for future (?:roles|opportunities|openings)\b|"
    r"\bevergreen (?:role|posting|requisition)\b|\bgeneral application\b", re.I)
_PAID_PROGRAM_RE = re.compile(
    r"\bfellowship\b|\b(?:course|training|program(?:me)?|tuition|enrol?lment) fees?\b|"
    r"\bpay (?:a |the )?(?:fee|tuition)\b|\bpaid (?:training|bootcamp|program(?:me)?)\b", re.I)
_PHD_RE = re.compile(
    r"\bpost-?doc(?:toral)?\b|\bph\.?d\.?\W+(?:is\s+)?(?:required|mandatory)|"
    r"\b(?:requires?|must\s+(?:have|hold)|need)\s+(?:a\s+)?ph\.?d", re.I)
_STUDENT_RE = re.compile(
    r"\b(?:currently|presently)\s+(?:enrolled|pursuing)\b|\bmust be (?:a )?(?:current )?student\b|"
    r"\benrolled in (?:a|an) (?:university|college|degree|bachelor|master|accredited)|"
    r"\bfinal[- ]year students?\b|\bstudents? only\b|\breturning to school\b", re.I)
# kind -> (title pattern, body pattern)
_NON_JOB_RES: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "talent_pool": (_TALENT_POOL_TITLE_RE, _TALENT_POOL_BODY_RE),
    "paid_program": (_PAID_PROGRAM_RE, _PAID_PROGRAM_RE),
    "phd_required": (_PHD_RE, _PHD_RE),
    "student_only": (_STUDENT_RE, _STUDENT_RE),
}
_CLEARANCE_RE = re.compile(
    r"(?<!no )\b(?:security clearance|ts/sci|secret clearance|active clearance|clearance required)\b", re.I)
_CITIZEN_RE = re.compile(
    r"\b(?:must be|need to be|have to be|required to be)\s+(?:a\s+)?(?:u\.?s\.?|american|uk|british|eu|canadian|australian)\s+"
    r"(?:citizen|national|resident)s?\b|\b(?:u\.?s\.?)\s+citizen(?:ship)?\s+(?:is\s+)?required\b", re.I)
_CERT_RE = re.compile(
    r"\bcertifications?\W+(?:is |are )?(?:mandatory|required|a must|compulsory)|"
    r"\b(?:mandatory|required)\W+(?:\w+\W+){0,3}certifications?\b|"
    r"\bmust (?:have|hold|possess)\W+(?:\w+\W+){0,4}certifications?\b", re.I)
_DEGREE_RE = re.compile(r"\b(?:bachelor|b\.?\s?tech|b\.?\s?sc|master|m\.?\s?tech|degree)\w*", re.I)
_DEGREE_WAIVER_RE = re.compile(r"or equivalent|or related|equivalent experience|in lieu", re.I)


def _language_patterns(prof: Profile) -> dict[str, re.Pattern[str]]:
    patterns = {}
    for name, alts in _LANGUAGES.items():
        if name in prof.languages:
            continue
        patterns[name] = re.compile(
            rf"\b{_FLUENCY}\W+(?:\w+\W+){{0,3}}?(?:{alts})\b|"
            rf"\b(?:{alts})\W+(?:\w+\W+){{0,3}}?(?:{_FLUENCY}|required|mandatory|a must|essential)\b", re.I)
    return patterns


def _language_required(lines: list[Line], prof: Profile) -> list[Signal]:
    signals = []
    patterns = _language_patterns(prof)
    for line in lines:
        if line.section == PREFERRED:
            continue
        clauses = [c for c in re.split(r"[;.,]", line.text) if not _PREFERRED_CLAUSE_RE.search(c)]
        for name, pattern in patterns.items():
            if any(pattern.search(clause) for clause in clauses):
                signals.append(Signal(f"desc_{line.section}", "constraint", -1, 1.0,
                                      f"language_required:{name}", True))
                return signals
    return signals


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W\d_]+", text.lower())


def predominant_foreign_language(text: str) -> str | None:
    """Stopword-ratio language ID for de/fr/es/nl/pt, plus a CJK-share check for ja/zh."""
    compact = re.sub(r"\s+", "", text)
    if compact and len(re.findall(r"[぀-ヿ㐀-鿿]", compact)) / len(compact) >= 0.2:
        return "cjk"
    words = _words(text)
    if len(words) < _MIN_WORDS_FOR_LANGUAGE_ID:
        return None
    ratios = {lang: sum(w in sw for w in words) / len(words) for lang, sw in _STOPWORDS.items()}
    foreign_lang = max((lang for lang in ratios if lang != "en"), key=lambda lang: ratios[lang])
    if ratios[foreign_lang] >= 0.12 and ratios[foreign_lang] > 1.5 * ratios["en"]:
        return foreign_lang
    return None


def _non_job_signals(title: str, lines: list[Line]) -> list[Signal]:
    signals = []
    body = "\n".join(l.text for l in lines if l.section != PREFERRED)
    for kind, (title_re, body_re) in _NON_JOB_RES.items():
        for source, pattern, haystack in (("title", title_re, title), ("desc_other", body_re, body)):
            if pattern.search(haystack):
                signals.append(Signal(source, "constraint", -1, 1.0, f"non_job:{kind}", True))
                break
    return signals


def _hard_requirement_signals(lines: list[Line]) -> list[Signal]:
    signals = []
    body = [l for l in lines if l.section != PREFERRED]
    if any(_CLEARANCE_RE.search(l.text) for l in body):
        signals.append(Signal("desc_other", "constraint", -1, 1.0, "security_clearance", True))
    if any(_CITIZEN_RE.search(l.text) for l in body):
        signals.append(Signal("desc_other", "constraint", -1, 1.0, "citizenship_required", True))
    return signals


def _weak_requirement_signals(lines: list[Line], prof: Profile) -> list[Signal]:
    signals = []
    required = [l.text for l in lines if l.section == REQUIRED]
    if any(_CERT_RE.search(l.text) for l in lines if l.section != PREFERRED):
        signals.append(Signal("desc_required", "constraint", -1, 0.7, "certification_mandatory"))
    if not prof.has_bachelor and any(
            _DEGREE_RE.search(t) and not _DEGREE_WAIVER_RE.search(t) for t in required):
        signals.append(Signal("desc_required", "constraint", -1, 0.15, "degree_required"))
    return signals


def constraint_signals(title: str, text: str, lines: list[Line], prof: Profile) -> list[Signal]:
    signals = _language_required(lines, prof)
    foreign = predominant_foreign_language(text)
    if foreign:
        signals.append(Signal("desc_other", "constraint", -1, 1.0, f"description_non_english:{foreign}", True))
    title_word = _TITLE_NON_ENGLISH_RE.search(title)
    if title_word:
        signals.append(Signal("title", "constraint", -1, 0.4, f"title_non_english:{title_word.group(1).lower()}"))
    return (signals + _non_job_signals(title, lines) + _hard_requirement_signals(lines)
            + _weak_requirement_signals(lines, prof))
