"""submission_gate.py — Hard pre-submission validation gate.

Runs once, immediately before a job's cached cover letter + identity payload
(name, phone, email, links, company) is allowed to reach any channel
submitter (indeed_apply.py, ats_apply.py, direct_form.py). A single failed
check blocks the job. All failed checks are collected and reported together
so the failure reason is informative, but the outcome itself is binary:
pass (empty list) or block (non-empty list) — there is no warning/soft-fail
mode.

Canonical identity values come from config.yaml's `profile:` block, loaded
the same way src/answers.py loads it (see `validate_job_submission`, which
calls `answers._profile()`) — never re-parsed or hardcoded a second time
here.

This module only runs at submission time. It does not touch, call, or
duplicate any cover-letter *generation*-time logic in src/tailor.py.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent.parent
FACTS_PATH = ROOT / "profile" / "facts.md"

# The one historically-observed transposed phone number (9106990136 -> 9016990136:
# the 1 and 0 swapped). Called out as its own named check, in addition to the
# general canonical-mismatch check below, per the incident this gate exists for.
KNOWN_BAD_PHONE = "9016990136"

# General placeholder patterns — not a fixed list of specific tokens. Verified against
# every real letter in output/tailored/*.txt: 225/1482 contain a genuine unresolved
# bracket placeholder (almost all "[Your Name]" / "[Hiring Manager]" / "[Company Name]"),
# exactly one contains a stray curly marker ("{devlogic}"), and zero legitimate/clean
# letters use '[' or '{' for anything else (no markdown links, no code, no citations).
BRACKET_PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{1,80}\]")
CURLY_PLACEHOLDER_RE = re.compile(r"\{[^{}\n]{1,80}\}")

# Phone-like digit runs inside free text (cover letters), e.g. "+91 9106990136" or
# "9106990136". Bounded length keeps it from matching unrelated numbers in prose
# ("220 rental units", "40+ hours", "70k+ LOC", "May 2026").
_PHONE_CANDIDATE_RE = re.compile(r"\+?\d[\d\-.\s]{7,16}\d")

# Company values that mean "we never actually found a company" (src/discover.py
# defaults to the literal string "Unknown" when scraping fails to extract one).
# Compared against `_alnum_key(company)` (folded, punctuation/whitespace removed), so
# "N/A", "n.a.", "N\A" -> "na" and "Not-Disclosed" / "not disclosed" -> "notdisclosed".
_BAD_COMPANY_KEYS = frozenset({
    "unknown", "na", "none", "null", "tbd", "confidential", "notdisclosed",
})

# Generic/placeholder-ish company references inside cover-letter prose, e.g.
# "...role at Unknown" or "...position at TBD".
_GENERIC_COMPANY_WORDS = ("unknown", "n/a", "tbd", "confidential")

LINK_FIELDS = ("linkedin", "github", "portfolio")


class GateConfigError(Exception):
    """The gate cannot establish canonical truth (facts.md / profile missing, unreadable,
    empty or malformed). Always fail closed: run_submission_gate turns it into a finding."""


class GateContractError(Exception):
    """A validator returned something other than a list of non-blank str findings."""


# Explicit Cyrillic/Greek -> Latin look-alike table (lower case; upper-case twins are
# derived below). Deliberately small: only letters visually indistinguishable from a
# Latin letter in common fonts.
_HOMOGLYPH_PAIRS = {
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
    "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
    "ԛ": "q", "ԝ": "w", "һ": "h",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
}
_HOMOGLYPH_TABLE = {ord(k): v for k, v in _HOMOGLYPH_PAIRS.items()}
_HOMOGLYPH_TABLE.update({ord(k.upper()): v.upper() for k, v in _HOMOGLYPH_PAIRS.items()})


def fold_preserving_case(raw: str) -> str:
    """NFKC, drop format chars (Unicode Cf: zero-width space/joiner, BOM, soft hyphen,
    bidi marks), drop combining marks, fold look-alike letters to Latin. Case is kept so
    capitalisation cues still work."""
    s = unicodedata.normalize("NFKC", raw)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.translate(_HOMOGLYPH_TABLE)


def fold_text(raw: str) -> str:
    return fold_preserving_case(raw).casefold()


def _alnum_key(raw: str) -> str:
    """Folded text with every non-alphanumeric char removed ('' for punctuation-only)."""
    return re.sub(r"[\W_]+", "", fold_text(raw))


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _digits_only(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def normalize_phone(raw: str | None) -> str:
    """Last 10 digits — strips spaces/dashes/dots/'+'/country-code formatting so
    '+91 9106990136', '91-9106990136' and '9106990136' all normalize identically."""
    d = _digits_only(raw)
    return d[-10:] if len(d) >= 10 else d


def normalize_name(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip()).lower()


def normalize_email(raw: str | None) -> str:
    return (raw or "").strip().lower()


def normalize_link(raw: str | None) -> str:
    """Scheme/www/trailing-slash-insensitive: 'https://www.linkedin.com/in/x' and
    'linkedin.com/in/x' compare equal."""
    s = (raw or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


def find_placeholders(text: str | None) -> list[str]:
    """Every unresolved bracket/curly template token found in `text`."""
    if not text:
        return []
    return BRACKET_PLACEHOLDER_RE.findall(text) + CURLY_PLACEHOLDER_RE.findall(text)


def _phone_candidates(text: str | None) -> list[str]:
    out = []
    for m in _PHONE_CANDIDATE_RE.finditer(text or ""):
        digits = _digits_only(m.group(0))
        if 9 <= len(digits) <= 13:
            out.append(digits)
    return out


# ---------------------------------------------------------------------------
# Field-level checks
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES = frozenset({
    "inc", "llc", "ltd", "corp", "gmbh", "co", "the",
    "limited", "corporation", "incorporated", "pvt", "llp", "plc",
})


def company_tokens(raw: str) -> tuple[str, ...]:
    """Comparison tokens for a company name: folded, possessive 's removed, punctuation
    split, legal suffixes (and 'the') dropped. If dropping would leave nothing (a company
    literally named 'The Company'), the undropped tokens are used instead."""
    folded = re.sub(r"(?<=\w)['’]s\b", "", fold_text(raw))
    tokens = re.sub(r"[\W_]+", " ", folded).split()
    return tuple([t for t in tokens if t not in _LEGAL_SUFFIXES] or tokens)


def validate_company(company: object, canonical_name: str | None = None) -> list[str]:
    """Rejects non-strings (checked BEFORE any str() coercion), empty/punctuation-only
    values, known placeholders ('Unknown', 'N/A', 'NA', 'None', 'null', '-', 'TBD',
    'Confidential', 'Not disclosed' — after Unicode/homoglyph/punctuation normalisation),
    and the candidate's own name used as the company."""
    if not isinstance(company, str):
        return [f"company is not a string (got {type(company).__name__})"]
    key = _alnum_key(company)
    if not key:
        return ["company is empty, whitespace-only, or punctuation-only"]
    if key in _BAD_COMPANY_KEYS:
        return [f"company is a known placeholder value: '{company}'"]
    if isinstance(canonical_name, str) and _alnum_key(canonical_name) \
            and company_tokens(company) == company_tokens(canonical_name):
        return [f"company '{company}' is the candidate's own name"]
    return []


# --- Company named inside the cover letter must be the job's company ----------------

# Cue phrases after which a company name is expected. Deliberately narrow: bare
# "at/with/for + Capitalised" was measured against the real letters and is dominated by
# technology and project names ("with React", "at Neuro-Zenith"), so it is NOT a cue.
_DIRECT_CUE_RE = re.compile(r"\b(?:dear|join(?:ing)?|applying\s+to)\s+", re.I)
_PLACE_CUE_RE = re.compile(
    r"\b(?:work(?:ing)?\s+at|(?:role|position|opportunity|opening|vacancy|internship|job|team|manager"
    r"|recruiter)\s+(?:at|with))\s+",
    re.I,
)
# Candidate-history context: "my current role at Neuro-Zenith", "prior to joining Shade
# Ledger" describe the candidate's own past employers/projects, not the target company.
_HISTORY_WORD_RE = re.compile(
    r"\b(?:my|our|his|her|their|previous|current|prior|former|past|earlier|last)\b", re.I)
_JOIN_HISTORY_RE = re.compile(r"\b(?:prior\s+to|before|after|since|upon)\s+$", re.I)
_HISTORY_WINDOW_WORDS = 8
_NAME_CONNECTORS = frozenset({"&", "of", "and", "de"})
_TITLE_TOKENS = frozenset({"mr", "mrs", "ms", "dr", "prof", "mx"})
# Words that make a greeting generic ("Dear Hiring Manager", "Dear Engineering Team").
# A mention made only of these is ignored; they are also stripped from a mixed mention
# so "Globex Hiring Team" is compared as "globex".
_GENERIC_WORDS = frozenset({
    "hiring", "recruiting", "recruitment", "talent", "acquisition", "people", "hr", "human",
    "resources", "engineering", "team", "teams", "manager", "managers", "committee",
    "department", "recruiter", "recruiters", "staff", "sir", "madam", "or", "and", "the",
    "your", "our", "my", "this", "all", "everyone", "there", "folks", "whom", "it",
    "may", "concern", "to", "hello",
})
_MAX_NAME_TOKENS = 6
_NAME_STOP_CHARS = ',;:!?)"”’]'
_NAME_OPENERS = '("“‘'


def _is_name_token(token: str) -> bool:
    # '[' / '{' openers are template placeholders: owned by the placeholder check, not a name.
    core = token.lstrip(_NAME_OPENERS)
    return bool(core) and (core[0].isupper() or core[0].isdigit())


def _collect_name(rest: str) -> list[str]:
    """Capitalised token run at the start of `rest` (one line), connectors allowed only
    between capitalised tokens; stops after a token carrying trailing punctuation."""
    name: list[str] = []
    for raw in rest.split("\n", 1)[0].split():
        if len(name) >= _MAX_NAME_TOKENS:
            break
        trailing = raw.endswith(tuple(_NAME_STOP_CHARS)) or raw.endswith(".")
        token = raw.strip(_NAME_OPENERS).rstrip(_NAME_STOP_CHARS + ".")
        if not name and token.lower().rstrip(".") in _TITLE_TOKENS:
            continue
        if _is_name_token(raw) or (name and token.lower() in _NAME_CONNECTORS):
            name.append(token)
            if trailing:
                break
            continue
        break
    while name and name[-1].lower() in _NAME_CONNECTORS:
        name.pop()
    return name


def _is_history_context(text: str, cue: re.Match[str]) -> bool:
    before = re.split(r"[.!?\n]", text[:cue.start()])[-1]
    if cue.re is _DIRECT_CUE_RE:
        return bool(_JOIN_HISTORY_RE.search(before))
    return bool(_HISTORY_WORD_RE.search(" ".join(before.split()[-_HISTORY_WINDOW_WORDS:])))


def extract_company_mentions(text: str) -> list[str]:
    """Company-name candidates named in the letter via the cue phrases above, skipping
    cues that sit in candidate-history context."""
    folded = fold_preserving_case(text)
    mentions: list[str] = []
    for cue_re in (_DIRECT_CUE_RE, _PLACE_CUE_RE):
        for m in cue_re.finditer(folded):
            name = _collect_name(folded[m.end():]) if not _is_history_context(folded, m) else []
            if name:
                mentions.append(" ".join(name))
    return mentions


def _mention_matches_company(mention: str, company_tokens_: tuple[str, ...]) -> bool:
    """True for generic referents and for a mention equal to / token-contained by /
    token-containing the job company."""
    tokens = tuple(t for t in company_tokens(mention) if t not in _GENERIC_WORDS)
    if not tokens:
        return True
    mention_set, company_set = set(tokens), set(company_tokens_)
    return (mention_set <= company_set or company_set <= mention_set
            or "".join(tokens) == "".join(company_tokens_))


def validate_company_consistency(text: str | None, company: str) -> list[str]:
    """Every non-generic company named in the letter must match the job's company
    (legal suffixes, case, punctuation, Unicode look-alikes ignored)."""
    if not text:
        return []
    expected = company_tokens(company)
    problems: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for mention in extract_company_mentions(text):
        key = company_tokens(mention)
        if key in seen or _mention_matches_company(mention, expected):
            continue
        seen.add(key)
        problems.append(
            f"cover letter names a different company ('{mention}') than the job's company ('{company}')")
    return problems


def _validate_phone_value(value: str | None, canonical_phone: str) -> list[str]:
    if value is None or not str(value).strip():
        return []
    norm = normalize_phone(value)
    canon = normalize_phone(canonical_phone)
    if norm == KNOWN_BAD_PHONE:
        return [f"phone '{value}' is the known transposed phone number '{KNOWN_BAD_PHONE}'"]
    if norm != canon:
        return [f"phone '{value}' does not match the canonical phone '{canonical_phone}'"]
    return []


def _validate_text_field(value: str | None, canonical_value: str, label: str, normalizer) -> list[str]:
    if value is None or not str(value).strip():
        return []
    if normalizer(value) != normalizer(canonical_value):
        return [f"{label} '{value}' does not match the canonical {label} '{canonical_value}'"]
    return []


def validate_links(payload: dict, canonical: dict) -> list[str]:
    """If the payload includes linkedin/github/portfolio, each must match the canonical
    value (scheme/www-insensitive)."""
    problems = []
    for field in LINK_FIELDS:
        value = payload.get(field)
        canon_value = canonical.get(field)
        if not value or not canon_value:
            continue
        if normalize_link(value) != normalize_link(canon_value):
            problems.append(f"{field} '{value}' does not match the canonical {field} '{canon_value}'")
    return problems


def _phone_problems_in_text(text: str, canonical_phone: str) -> list[str]:
    problems: list[str] = []
    canon = normalize_phone(canonical_phone)
    seen: set[str] = set()
    for digits in _phone_candidates(text):
        norm = normalize_phone(digits)
        if norm in seen:
            continue
        seen.add(norm)
        if norm == KNOWN_BAD_PHONE:
            problems.append(
                f"cover letter contains the known transposed phone number '{KNOWN_BAD_PHONE}'")
        elif norm != canon:
            problems.append(
                f"cover letter contains a phone number ('{digits}') that does not match the canonical phone")
    return problems


def validate_cover_letter(text: str | None, canonical: dict) -> list[str]:
    """Placeholder tokens, a wrong/transposed phone embedded in the prose, the employer
    being addressed by the candidate's own name, and generic/placeholder company
    references — all inside the cached cover-letter text itself."""
    if not text:
        return []
    problems: list[str] = []
    placeholders = find_placeholders(text)
    if placeholders:
        uniq = sorted(set(placeholders))
        problems.append(f"cover letter contains unresolved template placeholder(s): {', '.join(uniq)}")
    problems += _phone_problems_in_text(text, canonical["phone"])
    name = canonical.get("name") or ""
    if name:
        if re.search(rf"\b(?:at|with|for)\s+{re.escape(name)}\b", text, re.I) or \
           re.search(rf"\bdear\s+{re.escape(name)}\b", text, re.I):
            problems.append(
                f"cover letter addresses the employer using the candidate's own name "
                f"('{name}') instead of a company name")
    for bad in _GENERIC_COMPANY_WORDS:
        if re.search(rf"\b(?:at|with|for)\s+{re.escape(bad)}\b", text, re.I):
            problems.append(f"cover letter contains a malformed/generic company reference ('{bad}')")
    return problems


# ---------------------------------------------------------------------------
# Canonical-identity cross-check: config.yaml vs. profile/facts.md
# ---------------------------------------------------------------------------
#
# Every check above compares a payload against `canonical` (config.yaml's `profile:`
# block, as loaded by answers._profile()). But config.yaml is itself just a file that
# can be hand-edited and drift from the truth — which is exactly what caused the
# historical incident: config.yaml's phone field got silently edited to a transposed
# value, independent of profile/facts.md. A payload-vs-canonical check alone cannot
# catch that, because at the one real call site the payload IS built from canonical —
# it would always agree with itself.
#
# profile/facts.md declares itself the repo's sole source of truth ("Single source of
# truth for every LLM prompt in Hermes... The LLM may ONLY state facts written here.").
# This section parses its `## Contact` block independently of config.yaml/answers.py,
# so config.yaml has something external to be cross-checked against.

_FACTS_CONTACT_FIELD_RE = re.compile(r"^-\s*([A-Za-z]+)\s*:\s*(.+?)\s*$")
_FACTS_CONTACT_SECTION_RE = re.compile(r"^##\s*Contact\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)


REQUIRED_FACTS_FIELDS = ("name", "phone", "email", "github", "linkedin", "portfolio")


def _parse_facts_contact(text: str) -> dict[str, str]:
    """Pure parse of facts.md text; raises GateConfigError on anything not fully usable."""
    if not text.strip():
        raise GateConfigError("profile/facts.md is empty")
    section_match = _FACTS_CONTACT_SECTION_RE.search(text)
    if not section_match:
        raise GateConfigError("profile/facts.md has no '## Contact' section")
    fields: dict[str, str] = {}
    for line in section_match.group(1).splitlines():
        m = _FACTS_CONTACT_FIELD_RE.match(line.strip())
        if m:
            fields[m.group(1).strip().lower()] = m.group(2).strip()
    missing = [k for k in REQUIRED_FACTS_FIELDS if not fields.get(k)]
    if missing:
        raise GateConfigError(f"profile/facts.md '## Contact' is missing required field(s): {', '.join(missing)}")
    if len(_digits_only(fields["phone"])) < 10:
        raise GateConfigError("profile/facts.md phone has fewer than 10 digits")
    if "@" not in fields["email"]:
        raise GateConfigError("profile/facts.md email is not an email address")
    return fields


@lru_cache(maxsize=1)
def _load_facts_contact() -> dict[str, str]:
    """Independently parses facts.md's `## Contact` section into
    {"name", "location", "email", "phone", "github", "linkedin", "portfolio"} (lowercased
    keys). Simple and tolerant of the file's existing fixed bullet format — not a general
    markdown parser. Memoized: it's a static file, no need to re-read it per job in a batch.

    Fails CLOSED: a missing/unreadable/empty/malformed file, a missing `## Contact`
    section, or any missing required field raises GateConfigError. Exceptions are never
    cached by lru_cache, so a transient failure cannot freeze into a permanent bypass."""
    try:
        text = FACTS_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise GateConfigError(f"profile/facts.md unreadable: {type(exc).__name__}: {exc}") from exc
    return _parse_facts_contact(text)


# (canonical profile key, facts.md Contact key, normalizer)
_CANONICAL_VS_FACTS_FIELDS = (
    ("name", "name", normalize_name),
    ("phone", "phone", normalize_phone),
    ("email", "email", normalize_email),
    ("github", "github", normalize_link),
    ("linkedin", "linkedin", normalize_link),
    ("portfolio", "portfolio", normalize_link),
)


def _is_nonblank_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_canonical_identity(canonical: dict) -> list[str]:
    """Cross-checks config.yaml's `profile:` block (`canonical`) against the
    independently-parsed profile/facts.md `## Contact` section. Any mismatch means the
    canonical identity itself is corrupted — every job must be blocked, not just one
    with a bad payload, since every job's payload is built from this same canonical
    dict (this is the exact failure mode of the original incident: one bad config.yaml
    edit silently corrupted an entire batch of outgoing applications).

    A required field that is missing/blank on EITHER side is itself a problem — never a
    silent skip."""
    if not isinstance(canonical, dict):
        raise GateConfigError(f"canonical profile is not a mapping (got {type(canonical).__name__})")
    facts = _load_facts_contact()
    problems: list[str] = []
    for canon_key, facts_key, normalizer in _CANONICAL_VS_FACTS_FIELDS:
        canon_val = canonical.get(canon_key)
        facts_val = facts.get(facts_key)
        if not _is_nonblank_str(canon_val):
            problems.append(f"config.yaml profile is missing required field '{canon_key}'")
        elif not _is_nonblank_str(facts_val):
            problems.append(f"profile/facts.md is missing required field '{facts_key}'")
        elif normalizer(canon_val) != normalizer(facts_val):
            if canon_key == "phone" and normalize_phone(canon_val) == KNOWN_BAD_PHONE:
                problems.append(
                    f"config.yaml phone '{canon_val}' is the known transposed phone "
                    f"number '{KNOWN_BAD_PHONE}' — canonical identity itself is corrupted")
            else:
                problems.append(
                    f"config.yaml {canon_key} '{canon_val}' does not match profile/facts.md "
                    f"{facts_key} '{facts_val}' — canonical identity itself is corrupted")
    return problems


# ---------------------------------------------------------------------------
# Top-level gate
# ---------------------------------------------------------------------------

def validate_submission(payload: dict, cover_letter: str | None, canonical: dict) -> list[str]:
    """payload: {"name", "phone", "email", "linkedin", "github", "portfolio", "company"} —
    the identity + company fields about to reach a channel submitter.
    cover_letter: the cached cover-letter text about to be pasted/uploaded into the form.
    canonical: the candidate's profile dict (config.yaml's `profile:` block).

    Returns every failed check's human-readable reason; an empty list means the job is
    safe to submit. The caller (apply.py) must treat ANY non-empty result as a hard block.
    """
    problems: list[str] = []
    company_problems = validate_company(payload.get("company"), canonical.get("name"))
    problems += company_problems
    if not company_problems:
        problems += validate_company_consistency(cover_letter, payload["company"])
    problems += _validate_text_field(payload.get("name"), canonical["name"], "name", normalize_name)
    problems += _validate_phone_value(payload.get("phone"), canonical["phone"])
    problems += _validate_text_field(payload.get("email"), canonical["email"], "email", normalize_email)
    problems += validate_links(payload, canonical)
    problems += validate_cover_letter(cover_letter, canonical)
    return problems


def _load_canonical_profile() -> dict:
    """answers._profile(), validated to carry the fields the gate indexes directly.
    Any failure (missing `profile:` block, bad YAML, import error) surfaces as an
    exception that run_submission_gate converts into a finding."""
    from answers import _profile  # lazy: avoids importing answers' llm dependency chain
    canonical = _profile()        # at apply.py import time for callers that never apply
    if not isinstance(canonical, dict):
        raise GateConfigError(f"config.yaml profile is not a mapping (got {type(canonical).__name__})")
    missing = [k for k in ("name", "phone", "email") if not _is_nonblank_str(canonical.get(k))]
    if missing:
        raise GateConfigError(f"config.yaml profile is missing required field(s): {', '.join(missing)}")
    return canonical


def validate_job_submission(job: dict, cover_letter: str | None) -> list[str]:
    """Convenience wrapper used by apply.py's dispatch choke point.

    Builds the payload from the job's own `company` field plus the canonical profile —
    loaded via the exact same mechanism src/answers.py uses (`answers._profile()`, i.e.
    config.yaml's `profile:` block) rather than re-parsing config.yaml or hardcoding a
    second copy of the candidate's identity here — then runs the full gate.

    Also independently cross-checks that canonical profile against profile/facts.md
    (see `validate_canonical_identity`) on every call: if config.yaml has itself drifted
    from the repo's declared source of truth, every job is blocked, not just one with a
    bad payload.

    Returns list[str] findings. May raise (GateConfigError etc.); callers must go
    through run_submission_gate, which never raises.
    """
    canonical = _load_canonical_profile()
    problems = validate_canonical_identity(canonical)
    payload = {
        "name": canonical.get("name"),
        "phone": canonical.get("phone"),
        "email": canonical.get("email"),
        "linkedin": canonical.get("linkedin"),
        "github": canonical.get("github"),
        "portfolio": canonical.get("portfolio"),
        "company": job.get("company"),
    }
    problems += validate_submission(payload, cover_letter, canonical)
    return problems


def _enforce_findings_contract(findings: object) -> list[str]:
    """Validator contract: a list whose every element is a non-blank str. Anything else
    (None/False/True/0, tuple, str, list with a non-str or blank element) is a violation."""
    if not isinstance(findings, list):
        raise GateContractError(f"validator returned {type(findings).__name__}, expected list[str]")
    bad = [type(f).__name__ for f in findings if not _is_nonblank_str(f)]
    if bad:
        raise GateContractError(f"validator returned a malformed list: non-str/blank element(s) {bad[:3]}")
    return findings


def run_submission_gate(job: dict, cover_letter: str | None) -> list[str]:
    """THE shared, fail-closed entry point every submission path must use (apply.py's
    apply_one and both engine_apply drivers). Never raises: any Exception from profile/
    facts loading, canonical extraction, validation logic or a monkeypatched validator,
    and any contract violation, becomes a finding. Returns [] only for a genuinely
    clean list; any non-empty result is a hard, terminal block (VALIDATION_FAILED).

    `validate_job_submission` is resolved at call time so tests can monkeypatch it.
    BaseException (KeyboardInterrupt/SystemExit) is deliberately not caught."""
    try:
        return _enforce_findings_contract(validate_job_submission(job, cover_letter))
    except Exception as exc:  # fail-closed boundary: every failure mode must block, never escape
        return [f"submission gate failed closed: {type(exc).__name__}: {exc}"[:300]]
