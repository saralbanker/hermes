"""
qualify.py — Multi-evidence qualification engine.

    qualify(title, description, cfg) -> Qualification

Replaces single-signal title/years rejections. Evidence from the title and from the
requirement / preferred / other sections of the description is combined per dimension
(stack, seniority, constraint, role). One non-decisive source never rejects; rejection needs a
decisive signal or >= 2 corroborating sources. Positive fit evidence is also required: a long
description with no candidate-stack tokens is rejected, a stub with a neutral title is only a
low-confidence STRETCH. Candidate profile comes from config.yaml `qualification:`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from qualify_constraints import constraint_signals
from qualify_text import (OTHER, PREFERRED, REQUIRED, Line, Profile, Signal, YearsFinding,
                          build_profile, find_years, normalize_text, split_sections, years_matches)
from states import CORE, STRETCH

QUALIFY_VERSION = "qe-1"
QUALIFIED, REVIEW, REJECTED = "qualified", "review", "rejected"

SINGLE_SOURCE_CAP = 0.6      # one non-decisive source can never exceed this
REJECT_AT = 0.75
REVIEW_AT = 0.6
STRETCH_AT = 0.4
FIT_DISCOUNT = 0.25          # positive stack evidence discounts DESCRIPTION mismatches by up to this
STRONG_REQUIRED = 0.7        # a lone required-section signal this strong is never discounted
LONG_DESCRIPTION = 400       # shorter descriptions are "stubs": low confidence, never CORE
STUB_CONFIDENCE_CAP = 0.5

__all__ = ["Qualification", "Signal", "qualify", "to_columns", "QUALIFY_VERSION",
           "QUALIFIED", "REVIEW", "REJECTED"]


@dataclass(frozen=True)
class Qualification:
    decision: str                 # qualified | review | rejected
    tier: str | None              # CORE | STRETCH when qualified/review, None when rejected
    confidence: float             # 0..1, confidence in the decision itself
    fit_score: float              # 0..1, positive-fit strength
    required_years: int | None    # overall experience requirement actually used
    reasons: tuple[str, ...]      # most decisive first
    signals: tuple[Signal, ...]   # every piece of evidence considered
    version: str = QUALIFY_VERSION


@dataclass(frozen=True)
class _Ctx:
    title: str
    text: str
    lines: tuple[Line, ...]
    prof: Profile
    years: YearsFinding
    is_junior: bool
    academic_ok: bool   # java/kotlin/android acceptable: junior title/years or <= core_max years asked
    is_llm_app: bool

    def section(self, name: str) -> list[Line]:
        return [l for l in self.lines if l.section == name]

    @property
    def tech_text(self) -> str:
        """Requirement lines when a requirement section exists, else every non-preferred line."""
        required = self.section(REQUIRED)
        return "\n".join(l.text for l in (required or [l for l in self.lines if l.section != PREFERRED]))


# ---------------------------------------------------------------------------
# Stack evidence
# ---------------------------------------------------------------------------

_ROLE_NOUN = r"(?:developers?|engineers?|programmers?|consultants?|admin(?:istrator)?s?|architects?|specialists?)"
_ROLE_MODS = r"(?:cloud|backend|back-end|full[- ]?stack|software|platform|infrastructure|application|web|mobile|app)"
_SENIORITY_PREFIX_RE = re.compile(
    r"^\W*(?:(?:senior|sr\.?|junior|jr\.?|lead|staff|principal|associate|founding|intern)\s+)*", re.I)
_ROLE_TAIL_RE = re.compile(rf"^\s*(?:{_ROLE_MODS}\s+){{0,2}}{_ROLE_NOUN}\b", re.I)
_STRONG_PREFIX_RE = re.compile(
    r"(?:\d\+?\s*(?:years?|yrs?)\b[^.]{0,20}|\b(?:strong|expert|expertise|proficien\w*|deep|solid|"
    r"extensive|advanced)\b[^.]{0,25})$", re.I)
# (plain mention, strong mention) strengths per source
_ABSENT_STRENGTH = {REQUIRED: (0.5, 0.7), PREFERRED: (0.1, 0.1), OTHER: (0.15, 0.15)}
_PLATFORM_STRENGTH = {REQUIRED: (0.1, 0.5), PREFERRED: (0.0, 0.0), OTHER: (0.0, 0.0)}
_DEV_DUTY_RE = re.compile(
    r"\b(?:build|building|develop|developing|design|designing|implement|implementing|ship|shipping|"
    r"maintain|architect|create|creating|convert|converting)\b[^.\n]{0,60}\b(?:apis?|services?|applications?|apps?|systems?|backend|"
    r"back-end|features?|software|pipelines?|agents?|integrations?|platforms?|products?|websites?|"
    r"web ?pages?|interfaces|uis?|front-?ends?|components?|scripts?|tools?|bots?|automations?)\b|"
    r"\bwrit(?:e|ing)\s+(?:\w+\s+){0,2}(?:code|software|tests)\b", re.I)


_TOOLING_DUTY_RE = re.compile(
    r"\b(?:git|github|gitlab|docker|ci/?cd|linux|deployments?|scripting|shell scripts?|bash)\b", re.I)


def _is_junior_entry(ctx: _Ctx) -> bool:
    """Junior/intern/fresher title with no (or <= 1 year) overall experience requirement."""
    return bool(ctx.prof.junior_title.search(ctx.title)) and (
        ctx.years.value is None or ctx.years.value <= 1)


def _is_role_identity(title: str, match: re.Match[str], is_platform: bool) -> bool:
    """Token IS the role ("Java Developer", "DevOps Engineer") vs a secondary mention.
    A platform token that merely starts the title ("Azure AI Engineer") is not the role."""
    remainder = title[match.end():]
    starts_title = match.start() <= _SENIORITY_PREFIX_RE.match(title).end()
    if _ROLE_TAIL_RE.match(remainder):
        return True
    if starts_title and not re.sub(r"[\W_]+", "", remainder):
        return True  # the token is the whole title ("SRE")
    return starts_title and not is_platform


def _mismatch_matchers(ctx: _Ctx, in_title: bool = False) -> list[tuple[re.Pattern[str], bool]]:
    """(pattern, is_platform) for every stack family that counts as mismatch in this context.
    ML-training tokens are neutralised by LLM-app terms in the TITLE (title matching) or in the
    title / requirement lines (description matching) — never by description mentions alone for titles."""
    prof = ctx.prof
    matchers = [(prof.absent, False), (prof.platform, True)]
    if not ctx.academic_ok:
        matchers.append((prof.academic, False))
    if not in_title and not ctx.is_llm_app:
        matchers.append((prof.ml_training, False))
    return matchers


def _title_stack_signals(ctx: _Ctx) -> list[Signal]:
    best: tuple[float, str] | None = None
    has_core = bool(ctx.prof.title_core.search(ctx.title))
    junior_entry = _is_junior_entry(ctx)
    candidates: list[tuple[re.Match[str], bool, bool]] = []  # (match, is_platform, is_role_type)
    for pattern, is_platform in _mismatch_matchers(ctx, in_title=True):
        candidates += [(m, is_platform, False) for m in pattern.finditer(ctx.title)]
    if not ctx.prof.llm_app.search(ctx.title):
        candidates += [(m, True, True) for m in ctx.prof.ml_title.finditer(ctx.title)]
    candidates += [(m, True, True) for m in ctx.prof.role_identity.finditer(ctx.title)]
    for match, is_platform, is_role_type in candidates:
        identity = is_role_type or _is_role_identity(ctx.title, match, is_platform) \
            or (not is_platform and not has_core)
        if junior_entry and (is_platform or is_role_type):
            identity = False  # an intern/fresher "DevOps" title is a learner, not the role
        candidate = (0.6 if identity else 0.25,
                     f"title_{'role' if identity else 'secondary'}:{match.group(1).lower()}")
        best = max(best, candidate) if best else candidate
    signals = [Signal("title", "stack", -1, best[0], best[1])] if best else []
    core = ctx.prof.title_core.search(ctx.title)
    if core:
        signals.append(Signal("title", "stack", 1, 0.3, f"title_core:{core.group(1).lower()}"))
    academic = ctx.prof.academic.search(ctx.title)
    if academic and ctx.academic_ok:
        signals.append(Signal("title", "stack", 1, 0.3, f"academic_junior:{academic.group(1).lower()}"))
    return signals


def _desc_stack_signal(section: str, ctx: _Ctx) -> Signal | None:
    best, token, distinct = 0.0, "", set()
    lines = ctx.section(section)
    for pattern, is_platform in _mismatch_matchers(ctx):
        table = _PLATFORM_STRENGTH if is_platform else _ABSENT_STRENGTH
        for line in lines:
            for match in pattern.finditer(line.text):
                strong = bool(_STRONG_PREFIX_RE.search(line.text[max(0, match.start() - 45):match.start()]))
                strength = table[section][strong]
                if not is_platform:
                    distinct.add(match.group(1).lower())
                if strength > best:
                    best, token = strength, match.group(1).lower()
    no_core = not any(ctx.prof.core.search(l.text) for l in lines)
    if section == REQUIRED and len(distinct) >= 3 and no_core and best < 0.7:
        best = 0.7
    return Signal(f"desc_{section}", "stack", -1, best, f"desc_{section}:{token}") if best > 0 else None


def _stack_fit(ctx: _Ctx) -> float:
    """0..1 positive evidence: candidate-stack share of the technologies the requirements name."""
    prof, text = ctx.prof, ctx.tech_text
    core = {m.group(1).lower() for m in prof.core.finditer(text)}
    other = {m.group(1).lower() for pattern, is_platform in _mismatch_matchers(ctx) if not is_platform
             for m in pattern.finditer(text)}
    if ctx.academic_ok:
        core |= {m.group(1).lower() for m in prof.academic.finditer(text)}
    coverage = len(core) / (len(core) + len(other)) if core or other else 0.0
    return min(1.0, coverage + (0.3 if prof.title_core.search(ctx.title) else 0.0))


def _other_primary_stack(ctx: _Ctx) -> str | None:
    """A non-candidate primary stack/domain named by the requirement lines, if any."""
    text = ctx.tech_text
    for pattern, is_platform in _mismatch_matchers(ctx):
        if is_platform:
            found = {m.group(1).lower() for m in pattern.finditer(text)}
            if len(found) >= 2:
                return sorted(found)[0]
        else:
            match = pattern.search(text)
            if match:
                return match.group(1).lower()
    return None


def _positive_evidence_signals(ctx: _Ctx) -> list[Signal]:
    """Long descriptions must show candidate-stack evidence (title or requirements)."""
    if len(ctx.text) < LONG_DESCRIPTION:
        return []
    if ctx.prof.title_core.search(ctx.title) or ctx.prof.core_distinctive.search(ctx.tech_text):
        return []
    if ctx.academic_ok and ctx.prof.academic.search(ctx.tech_text + " " + ctx.title):
        return []
    if ctx.prof.llm_app.search(ctx.title) or ctx.prof.llm_app.search(ctx.text):
        return []  # LLM-application title / duties ("AI-powered workflows", "build agents") are core evidence
    other = _other_primary_stack(ctx)
    if other:
        return [Signal("desc_required", "stack", -1, 1.0, f"no_core_evidence+primary_other:{other}", True)]
    if _DEV_DUTY_RE.search(ctx.text) or _TOOLING_DUTY_RE.search(ctx.text) or _stack_fit(ctx) >= 0.5:
        return []
    return [Signal("desc_duties", "role", -1, 1.0, "no_dev_evidence", True)]


# ---------------------------------------------------------------------------
# Seniority evidence
# ---------------------------------------------------------------------------

_STAFF_RE = re.compile(
    r"(?<!technical )(?<!tech )\b(staff|principal|distinguished|architect|head of)\b(?!\s+augmentation)", re.I)
_LEAD_RE = re.compile(r"\b(tech(?:nical)? lead|team lead|lead)\b(?!\s+gen)", re.I)
_SENIOR_RE = re.compile(r"\b(senior|sr\.?|sde[- ]?(?:iii|3)|l[5-9]|engineer (?:iii|iv|3|4))(?![\w])", re.I)
_FOUNDING_RE = re.compile(r"\bfounding\b", re.I)
_LEADERSHIP_DUTY_RE = re.compile(
    r"\b(?:lead|manage|supervise|build|grow)\s+(?:a\s+)?(?:team|squad|group)\s+of\b|"
    r"\bmanage\s+engineers\b|\bpeople management\b|\bmentor and lead\b|\bown hiring\b|\bdirect reports\b", re.I)


def _title_seniority_signals(ctx: _Ctx) -> list[Signal]:
    signals = []
    for pattern, strength, label in ((_STAFF_RE, 0.6, "staff_plus"), (_LEAD_RE, 0.6, "lead"),
                                     (_SENIOR_RE, 0.3, "senior")):
        match = pattern.search(ctx.title)
        if match:
            signals.append(Signal("title", "seniority", -1, strength, f"title_{label}:{match.group(1).lower()}"))
            break
    low_years = ctx.years.kind == "overall" and ctx.years.value is not None \
        and ctx.years.value <= ctx.prof.core_max_years
    if low_years and signals and signals[0].detail.split(":")[0] in ("title_senior", "title_lead"):
        return []  # the requirement lines say <= core_max years: years evidence beats a misleading title
    if ctx.prof.junior_title.search(ctx.title):
        signals.append(Signal("title", "seniority", 1, 1.0, "title_junior"))
    return signals


def _years_signals(ctx: _Ctx) -> list[Signal]:
    years, prof = ctx.years, ctx.prof
    if years.value is None:
        return []
    detail = f"years:{years.value}:{years.kind}"
    if years.kind == "fallback":
        strength = 0.65 if years.value >= prof.knockout_years else 0.2 if years.value > prof.core_max_years else 0
        return [Signal("years", "seniority", -1, strength, detail)] if strength else []
    if years.value > prof.stretch_max_years or (years.has_minimum_cue and years.value >= prof.knockout_years):
        return [Signal("years", "seniority", -1, 1.0, detail, True)]
    if years.value > prof.core_max_years:
        return [Signal("years", "seniority", -1, 0.4 if years.kind == "overall" else 0.2, detail)]
    return []


def _leadership_signals(ctx: _Ctx) -> list[Signal]:
    if any(_LEADERSHIP_DUTY_RE.search(l.text) for l in ctx.lines if l.section != PREFERRED):
        return [Signal("desc_duties", "seniority", -1, 0.4, "leadership_duties")]
    return []


# ---------------------------------------------------------------------------
# Role evidence
# ---------------------------------------------------------------------------

_ENGINEERING_NOUN_RE = re.compile(
    r"\b(engineer(?:ing)?|developer|programmer|dev|sde|swe|software|coder|architect|full[- ]?stack|"
    r"back[- ]?end|front[- ]?end|devops|sre|mern|mean stack|data scientist)\b", re.I)
_NON_ENG_DUTY_RE = re.compile(
    r"\b(video (?:production|editing)|edit(?:ing)? videos?|motion graphics|content (?:creation|production)|"
    r"creative production|implementation support|customer implementations?|pre-?sales|solution demos?|"
    r"client onboarding|bi analyst|short[- ]form videos?|"
    r"(?:create|creating|produce|producing)\w* (?:\w+[- ]){0,3}videos?(?: content)?|(?:build|create|maintain)\w* (?:\w+ ){0,2}dashboards? (?:in|using|with) "
    r"(?:power bi|tableau|looker|excel))\b", re.I)


def _has_dev_duties(ctx: _Ctx) -> bool:
    distinct_core = {m.group(1).lower() for m in ctx.prof.core.finditer(ctx.text)}
    return len(distinct_core) >= 2 and bool(_DEV_DUTY_RE.search(ctx.text))


def _role_signals(ctx: _Ctx) -> list[Signal]:
    signals = []
    has_dev = _has_dev_duties(ctx)
    if not _ENGINEERING_NOUN_RE.search(ctx.title):
        if has_dev:
            signals.append(Signal("title", "role", -1, 0.6, "title_no_engineering_words:dev_duties_present"))
        else:
            signals.append(Signal("title", "role", -1, 1.0, "not_engineering_title", True))
    body = "\n".join(l.text for l in ctx.lines if l.section != PREFERRED)
    duties = {m.group(1).lower() for m in _NON_ENG_DUTY_RE.finditer(body)}
    if duties:
        has_dev_body = bool(_DEV_DUTY_RE.search(body))
        decisive = len(duties) >= 2 and not has_dev_body
        strength = 1.0 if decisive else 0.5 if has_dev_body else 0.7
        signals.append(Signal("desc_duties", "role", -1, strength,
                              f"non_engineering_duties:{sorted(duties)[0]}", decisive))
    return signals


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_DIMENSIONS = ("stack", "seniority", "constraint", "role")


def _dimension_mismatch(signals: list[Signal], dimension: str, fit: float) -> tuple[float, bool]:
    """1 - prod(1 - s) over DISTINCT sources; a lone non-decisive source is capped."""
    raw: dict[str, float] = {}
    for sig in signals:
        if sig.dimension != dimension or sig.polarity >= 0:
            continue
        if sig.is_decisive:
            return 1.0, True
        raw[sig.source] = max(raw.get(sig.source, 0.0), sig.strength)
    keep = 1.0
    for source, strength in raw.items():
        is_strong_required = source == "desc_required" and strength >= STRONG_REQUIRED
        if len(raw) == 1:
            strength = min(strength, SINGLE_SOURCE_CAP)
        if dimension == "stack" and source.startswith("desc_") and not is_strong_required:
            strength *= 1 - FIT_DISCOUNT * fit
        keep *= 1 - strength
    return round(1 - keep, 6), False


def _build_reasons(signals: list[Signal], mismatch: dict[str, tuple[float, bool]], fit: float) -> list[str]:
    reasons = []
    ordered = sorted(_DIMENSIONS, key=lambda d: (not mismatch[d][1], -mismatch[d][0]))
    for dim in ordered:
        value, decisive = mismatch[dim]
        if not decisive and value < 0.25:
            continue
        parts = sorted((s for s in signals if s.dimension == dim and s.polarity < 0),
                       key=lambda s: (not s.is_decisive, -s.strength))
        if decisive:
            parts = [s for s in parts if s.is_decisive]
        reasons.append(f"{dim}:" + "+".join(s.detail for s in parts))
    if fit > 0:
        reasons.append(f"fit:core_stack={fit:.2f}")
    return reasons or ["no_mismatch_evidence"]


def _decide(mismatch: dict[str, tuple[float, bool]]) -> str:
    worst = max(value for value, _ in mismatch.values())
    if any(decisive for _, decisive in mismatch.values()) or worst >= REJECT_AT:
        return REJECTED
    return REVIEW if worst >= REVIEW_AT else QUALIFIED


def _tier(ctx: _Ctx, mismatch: dict[str, tuple[float, bool]], decision: str, is_stub: bool) -> str | None:
    if decision == REJECTED:
        return None
    prof, years = ctx.prof, ctx.years
    is_senior_title = bool(_SENIOR_RE.search(ctx.title) or _FOUNDING_RE.search(ctx.title))
    mid_years = years.value is not None and years.value > prof.core_max_years  # any source: never CORE
    moderate = any(STRETCH_AT <= value < REJECT_AT for value, _ in mismatch.values())
    # zero professional years in the academic stack: allowed, but never CORE unless the title is junior
    uses_academic = not prof.junior_title.search(ctx.title) and bool(
        prof.academic.search(f"{ctx.title}\n{ctx.tech_text}"))
    return STRETCH if (is_senior_title or mid_years or moderate or is_stub or uses_academic
                       or decision == REVIEW) else CORE


def _confidence(decision: str, mismatch: dict[str, tuple[float, bool]], ctx: _Ctx, is_stub: bool) -> float:
    worst = max(value for value, _ in mismatch.values())
    if decision == REJECTED:
        return round(worst, 3)
    if decision == REVIEW:
        return 0.5
    completeness = 0.5 + (0.25 if len(ctx.text) >= LONG_DESCRIPTION else 0) \
        + (0.25 if ctx.section(REQUIRED) else 0)
    value = (1 - worst) * completeness
    return round(min(value, STUB_CONFIDENCE_CAP) if is_stub else value, 3)


def _with_title_years(found: YearsFinding, title: str, prof: Profile) -> YearsFinding:
    """Years stated in the TITLE ("10-15 Yrs", "4+ Years Exp", "min 5year") are decisive overall years."""
    in_title = [low for low, _kind, _min in years_matches(title, prof)]
    if not in_title or (found.value is not None and found.kind == "overall" and found.value >= max(in_title)):
        return found
    return YearsFinding(max(in_title), "overall", True)


def _make_context(title: str, description: str, cfg: dict) -> _Ctx:
    prof = build_profile(cfg)
    title, text = normalize_text(title), normalize_text(description)
    lines, _has_headers = split_sections(text)
    years = _with_title_years(find_years(lines, prof), title, prof)
    is_junior = bool(prof.junior_title.search(title)) or (
        years.kind == "overall" and years.value is not None and years.value <= 1)
    is_llm_app = bool(prof.llm_app.search(title)) or any(
        prof.llm_app.search(l.text) for l in lines if l.section == REQUIRED)
    low_years = years.value is not None and years.value <= prof.core_max_years
    return _Ctx(title, text, tuple(lines), prof, years, is_junior, is_junior or low_years, is_llm_app)


def _collect_signals(ctx: _Ctx) -> list[Signal]:
    signals = _title_stack_signals(ctx)
    signals += [s for s in (_desc_stack_signal(sec, ctx) for sec in (REQUIRED, PREFERRED, OTHER)) if s]
    signals += _positive_evidence_signals(ctx) + _title_seniority_signals(ctx) + _years_signals(ctx)
    signals += _leadership_signals(ctx) + _role_signals(ctx)
    signals += constraint_signals(ctx.title, ctx.text, list(ctx.lines), ctx.prof)
    return signals


def qualify(title: str, description: str, cfg: dict) -> Qualification:
    ctx = _make_context(title or "", description or "", cfg)
    signals = _collect_signals(ctx)
    fit = _stack_fit(ctx)
    mismatch = {dim: _dimension_mismatch(signals, dim, fit) for dim in _DIMENSIONS}
    decision = _decide(mismatch)
    is_stub = decision == QUALIFIED and len(ctx.text) < LONG_DESCRIPTION \
        and not ctx.prof.title_core.search(ctx.title)
    return Qualification(
        decision=decision,
        tier=_tier(ctx, mismatch, decision, is_stub),
        confidence=_confidence(decision, mismatch, ctx, is_stub),
        fit_score=round(fit, 3),
        required_years=ctx.years.value,
        reasons=tuple(_build_reasons(signals, mismatch, fit)),
        signals=tuple(signals),
    )


def to_columns(qual: Qualification) -> dict[str, object]:
    """jobs.qual_* column values (evidence = JSON of reasons + signals)."""
    evidence = {
        "reasons": list(qual.reasons),
        "required_years": qual.required_years,
        "fit_score": qual.fit_score,
        "signals": [{"source": s.source, "dimension": s.dimension, "polarity": s.polarity,
                     "strength": s.strength, "detail": s.detail, "decisive": s.is_decisive}
                    for s in qual.signals],
    }
    return {"qual_decision": qual.decision, "qual_confidence": qual.confidence,
            "qual_version": qual.version, "qual_evidence": json.dumps(evidence, separators=(",", ":"))}
