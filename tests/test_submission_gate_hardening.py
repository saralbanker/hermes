"""Hardening tests for submission_gate.py: fail-closed behaviour (exceptions, validator
contract, facts.md), company validation/consistency, and the apply.py redirect path.

No network, no browser. profile/facts.md and config.yaml are only ever READ; every
facts.md failure case runs against a tmp copy via monkeypatching `gate.FACTS_PATH`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import answers
import states as S
import submission_gate as gate

ROOT = Path(__file__).parent.parent
CANON = answers._profile()
REAL_FACTS_TEXT = (ROOT / "profile" / "facts.md").read_text(encoding="utf-8")
# Real, clean letter: addresses "Ahead" ("... NetSuite Developer role at Ahead ...").
CLEAN_LETTER = (ROOT / "output" / "tailored" / "ahead-netsuite-developer-cover.txt").read_text()
GOOD_JOB = {"company": "Ahead", "title": "NetSuite Developer"}

CFG = {"search": {"stretch_share": 0.3, "stretch_min_score": 7.5, "min_score": 6.5},
       "limits": {"min_delay_seconds": 0, "max_delay_seconds": 0, "total_per_day": 100,
                  "linkedin_per_day": 0, "other_per_day": 100},
       "resumes": {"default": "resumes/resume-fullstack.pdf"}}


@pytest.fixture(autouse=True)
def _fresh_facts_cache():
    """lru_cache must never leak a tmp-facts result into (or out of) another test."""
    gate._load_facts_contact.cache_clear()
    yield
    gate._load_facts_contact.cache_clear()


@pytest.fixture
def facts_file(tmp_path, monkeypatch):
    """Point the gate at a tmp copy of facts.md; returns a writer for its content."""
    path = tmp_path / "facts.md"
    monkeypatch.setattr(gate, "FACTS_PATH", path)

    def _write(text: str | bytes) -> Path:
        gate._load_facts_contact.cache_clear()
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path

    return _write


def _without_line(prefix: str) -> str:
    lines = [ln for ln in REAL_FACTS_TEXT.splitlines() if not ln.startswith(prefix)]
    assert len(lines) == len(REAL_FACTS_TEXT.splitlines()) - 1, prefix
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# A. Gate exception safety
# ---------------------------------------------------------------------------

def test_clean_job_passes_the_shared_entry_point():
    assert gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER) == []


def test_gate_exception_becomes_a_finding(monkeypatch):
    def boom(job, letter):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(gate, "validate_job_submission", boom)
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert findings and "RuntimeError" in findings[0] and "kaboom" in findings[0]


def test_base_exceptions_are_not_swallowed(monkeypatch):
    def interrupt(job, letter):
        raise KeyboardInterrupt
    monkeypatch.setattr(gate, "validate_job_submission", interrupt)
    with pytest.raises(KeyboardInterrupt):
        gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)


def test_missing_facts_md_fails_closed(facts_file):
    # facts_file points at a path that was never written
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert findings and "facts.md" in findings[0]


@pytest.mark.parametrize("content", [
    "", "   \n\n", "# Fact sheet\n\nno contact section at all\n",
    "## Contact\n- Name: Saral Banker\n",                       # required fields missing
    b"\xff\xfe\x00 not utf-8 \x80\x81",                          # unreadable as text
])
def test_empty_or_malformed_facts_md_fails_closed(facts_file, content):
    facts_file(content)
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert findings and "facts.md" in findings[0]


def test_unreadable_facts_md_path_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "FACTS_PATH", tmp_path)  # a directory: read_text raises OSError
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert findings and "unreadable" in findings[0]


@pytest.mark.parametrize("broken", [
    KeyError("profile"), RuntimeError("yaml exploded"), ImportError("no answers"),
])
def test_profile_extraction_failure_fails_closed(monkeypatch, broken):
    def bad_profile():
        raise broken
    monkeypatch.setattr(answers, "_profile", bad_profile)
    assert gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)


@pytest.mark.parametrize("profile", [None, [], "profile", {}, {"name": "Saral Banker"},
                                     dict(CANON, phone=""), dict(CANON, email=None)])
def test_malformed_profile_fails_closed(monkeypatch, profile):
    monkeypatch.setattr(answers, "_profile", lambda: profile)
    assert gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)


@pytest.mark.parametrize("job", [None, "company", 123, [], {"title": "no company key"}])
def test_malformed_job_fails_closed(job):
    assert gate.run_submission_gate(job, CLEAN_LETTER)


def test_non_string_cover_letter_fails_closed():
    assert gate.run_submission_gate(GOOD_JOB, 12345)


# ---------------------------------------------------------------------------
# B. Validator contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("returned", [
    None, False, True, 0, 1, "", "a finding", ("a finding",), (), {}, {"a": "b"}, object(),
    [None], [1], [("x",)], ["ok", None], [""], ["  "], [b"bytes"], ["ok", ["nested"]], [False],
])
def test_contract_violation_is_a_finding(monkeypatch, returned):
    monkeypatch.setattr(gate, "validate_job_submission", lambda job, letter: returned)
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert findings
    assert all(isinstance(f, str) and f.strip() for f in findings)


def test_valid_findings_list_passes_through_unchanged(monkeypatch):
    monkeypatch.setattr(gate, "validate_job_submission", lambda job, letter: ["one", "two"])
    assert gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER) == ["one", "two"]


def test_empty_list_is_the_only_clean_result(monkeypatch):
    monkeypatch.setattr(gate, "validate_job_submission", lambda job, letter: [])
    assert gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER) == []


# ---------------------------------------------------------------------------
# C. Company consistency (letter vs job["company"])
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("letter", [
    "Dear Globex,\n\nI'd like to apply.",
    "I would love to join Globex and build things.",
    "Working at Globex is my goal.",
    "I'm applying for the Backend Engineer role at Globex because it fits.",
    "I'm excited by the position at Globex Inc. and its mission.",
    "Dear Globex Hiring Team,\n\nHello.",
    "I'm thrilled about joining Globex.",
    "Dear Gl​obex,",                       # zero-width char inside the name
    "Dеar Globex,",                        # Cyrillic 'e' inside the cue word
    "Dear Globex Corp,",                   # NBSP
])
def test_letter_naming_another_company_is_rejected(letter):
    problems = gate.validate_company_consistency(letter, "Acme")
    assert problems and "different company" in problems[0]


@pytest.mark.parametrize("letter,company", [
    ("Dear Acme,\n\nHello.", "Acme"),
    ("Dear Acme Inc.,\n\nHello.", "Acme"),
    ("Dear Acme,\n\nHello.", "Acme Inc."),
    ("I'd love to join ACME Corp and help.", "Acme"),
    ("Dear Hiring Manager,\n\nHello.", "Acme"),
    ("Dear Hiring Team,\n\nHello.", "Acme"),
    ("Dear Sir or Madam,\n\nHello.", "Acme"),
    ("Dear Engineering Team,\n\nHello.", "Acme"),
    ("Dear Acme Hiring Team,\n\nHello.", "Acme"),
    ("I'd like to join the team and help.", "Acme"),
    ("I'd love to join your team at Acme.", "Acme"),
    ("Join Acme's team.", "Acme"),
    ("Dear Аcme,", "Acme"),                # Cyrillic capital A in the letter
    ("Dear Ac​me,", "Acme"),               # zero-width inside the right name
    ("Dear Acme,", "Аcme"),                # homoglyph in the job company
    ("Dear Smart Working,", "Smart Working Solutions"),   # mention contained by company
    ("Dear Acme Labs,", "Acme"),                          # mention contains company
    ("Dear Nestlé,", "Nestle"),
    ("I worked with React and Postgres at Neuro-Zenith.", "Acme"),   # not a cue
    ("In my current role at Neuro-Zenith I shipped a lot.", "Acme"),  # candidate history
    ("Prior to joining Shade Ledger, I freelanced.", "Acme"),         # candidate history
    ("Experience working with Terraform and Kubernetes.", "Acme"),    # tech, not a company
])
def test_consistent_or_generic_letters_pass(letter, company):
    assert gate.validate_company_consistency(letter, company) == []


def test_real_acme_letter_for_acme_passes_full_gate():
    letter = "Dear Acme Hiring Team,\n\nI'm applying for the role at Acme Inc. because I like it."
    assert gate.validate_submission(_payload(company="Acme"), letter, CANON) == []


def test_validate_submission_rejects_company_mismatch():
    letter = "Dear Globex,\n\nI'm applying for the role at Globex."
    problems = gate.validate_submission(_payload(company="Acme"), letter, CANON)
    assert any("different company" in p for p in problems)


def test_real_letter_passes_for_its_own_company_and_fails_for_another():
    assert gate.validate_job_submission({"company": "Ahead"}, CLEAN_LETTER) == []
    assert any("different company" in p
               for p in gate.validate_job_submission({"company": "Globex"}, CLEAN_LETTER))


def test_consistency_is_skipped_when_company_itself_is_invalid():
    # an invalid company is reported by validate_company; no second, misleading finding
    problems = gate.validate_submission(_payload(company="Unknown"), "Dear Globex,", CANON)
    assert problems and not any("different company" in p for p in problems)


def test_extract_company_mentions_basic():
    text = "Dear Globex,\nI'd like to join Initech and work at Hooli. Great role with Umbrella Corp."
    assert gate.extract_company_mentions(text) == ["Globex", "Initech", "Hooli", "Umbrella Corp"]


def test_extract_company_mentions_ignores_lowercase_follow_ons():
    assert gate.extract_company_mentions("I'd love to join the team.") == []
    assert gate.extract_company_mentions("Dear Hiring Manager,") == ["Hiring Manager"]


# ---------------------------------------------------------------------------
# D. Company hardening
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "Unknown", "UNKNOWN", "N/A", "n/a", "NA", "na", "n.a.", "N\\A", "N-A", "None", "none", "null",
    "NULL", "-", "--", "—", "...", "TBD", "tbd", "Confidential", "CONFIDENTIAL", "Not disclosed",
    "not-disclosed", "NOT_DISCLOSED", "  not   disclosed  ", None, "", "   ", "\t\n",
    "Unk​nown",                # zero-width space
    "﻿TBD",                    # BOM
    "Un­known",                # soft hyphen
    "Unknоwn",                 # Cyrillic o
    "ΤΒD",                # Greek capital Tau/Beta + D
    "N/Α",                     # Greek capital Alpha
    "ＴＢＤ",           # fullwidth TBD
    "Cоnfidential",            # Cyrillic o
    "​", "​-​",      # nothing but format chars / punctuation
])
def test_bad_company_values_are_rejected(value):
    assert gate.validate_company(value)


@pytest.mark.parametrize("value", [[], {}, [""], ["Acme"], {"name": "Acme"}, 123, 0, 1.5, True, False,
                                   b"Acme", ("Acme",), object()])
def test_non_string_company_is_rejected_without_coercion(value):
    # str(True) == "True", str([]) == "[]", str(123) == "123" would all look like "names"
    problems = gate.validate_company(value)
    assert problems and "not a string" in problems[0]


@pytest.mark.parametrize("value", ["Saral Banker", "SARAL BANKER", "  saral   banker ", "Saral Banker LLC",
                                   "Ѕaral Banker", "Saral​ Banker"])
def test_candidate_name_as_company_is_rejected(value):
    problems = gate.validate_company(value, CANON["name"])
    assert problems and "own name" in problems[0]


def test_candidate_name_check_needs_the_canonical_name():
    assert gate.validate_company("Saral Banker") == []   # optional param: opt-in


@pytest.mark.parametrize("value", ["Acme Corp", "Ahead", "Unknown Worlds Entertainment", "TBD Labs",
                                   "None of the Above Inc", "Banker Saral Holdings", "Na Ventures", "Nullify"])
def test_real_looking_companies_pass(value):
    assert gate.validate_company(value, CANON["name"]) == []


def test_candidate_name_company_threads_through_validate_submission_and_job_wrapper():
    letter = "Dear Hiring Manager,\n\nHello."
    assert any("own name" in p for p in
               gate.validate_submission(_payload(company="Saral Banker"), letter, CANON))
    assert any("own name" in p for p in
               gate.validate_job_submission({"company": "Saral Banker"}, letter))


@pytest.mark.parametrize("company", ["Unknown", "N/A", "-", "TBD", "Confidential", "Not disclosed",
                                     None, 123, [], {}, True, "​"])
def test_bad_company_blocks_via_run_submission_gate(company):
    assert gate.run_submission_gate({"company": company}, CLEAN_LETTER)


# ---------------------------------------------------------------------------
# E. facts.md fail-closed
# ---------------------------------------------------------------------------

def test_real_facts_md_loads_with_all_required_fields():
    facts = gate._load_facts_contact()
    assert all(facts[k] for k in gate.REQUIRED_FACTS_FIELDS)


def test_missing_facts_raises_gate_config_error(facts_file):
    with pytest.raises(gate.GateConfigError, match="unreadable"):
        gate._load_facts_contact()


@pytest.mark.parametrize("content,match", [
    ("", "empty"),
    ("  \n", "empty"),
    ("# no contact heading\n- Name: X\n", "no '## Contact'"),
    ("## Contact\n", "missing required"),
])
def test_malformed_facts_raises_gate_config_error(facts_file, content, match):
    facts_file(content)
    with pytest.raises(gate.GateConfigError, match=match):
        gate._load_facts_contact()


@pytest.mark.parametrize("field", ["- Name:", "- Email:", "- Phone:", "- GitHub:", "- LinkedIn:", "- Portfolio:"])
def test_each_required_contact_field_is_enforced(facts_file, field):
    facts_file(_without_line(field))
    with pytest.raises(gate.GateConfigError, match="missing required"):
        gate._load_facts_contact()


def test_blank_required_value_is_missing(facts_file):
    facts_file(REAL_FACTS_TEXT.replace("- Portfolio: orvion-co.vercel.app", "- Portfolio:   "))
    with pytest.raises(gate.GateConfigError, match="portfolio"):
        gate._load_facts_contact()


def test_implausible_phone_or_email_in_facts_is_malformed(facts_file):
    facts_file(REAL_FACTS_TEXT.replace("+91 9106990136", "12345"))
    with pytest.raises(gate.GateConfigError, match="phone"):
        gate._load_facts_contact()
    facts_file(REAL_FACTS_TEXT.replace("saralbanker1@gmail.com", "not-an-email"))
    with pytest.raises(gate.GateConfigError, match="email"):
        gate._load_facts_contact()


def test_contact_section_must_be_the_one_parsed(facts_file):
    # fields under a different heading do not count as Contact fields
    facts_file(REAL_FACTS_TEXT.replace("## Contact", "## Not Contact"))
    with pytest.raises(gate.GateConfigError, match="no '## Contact'"):
        gate._load_facts_contact()


def test_lru_cache_never_caches_a_failure(facts_file):
    path = facts_file("")  # broken first
    with pytest.raises(gate.GateConfigError):
        gate._load_facts_contact()
    path.write_text(REAL_FACTS_TEXT, encoding="utf-8")  # fixed WITHOUT cache_clear
    assert gate._load_facts_contact()["name"] == "Saral Banker"
    assert gate._load_facts_contact.cache_info().currsize == 1


def test_validate_canonical_identity_propagates_missing_facts(facts_file):
    with pytest.raises(gate.GateConfigError):
        gate.validate_canonical_identity(CANON)


@pytest.mark.parametrize("field", ["name", "phone", "email", "github", "linkedin", "portfolio"])
@pytest.mark.parametrize("bad_value", [None, "", "   ", 123, []])
def test_required_canonical_field_missing_is_a_problem_not_a_skip(field, bad_value):
    canonical = dict(CANON)
    canonical[field] = bad_value
    problems = gate.validate_canonical_identity(canonical)
    assert any(f"missing required field '{field}'" in p for p in problems)


def test_required_canonical_field_absent_key_is_a_problem():
    canonical = {k: v for k, v in CANON.items() if k != "github"}
    assert any("github" in p for p in gate.validate_canonical_identity(canonical))


def test_non_mapping_canonical_raises():
    with pytest.raises(gate.GateConfigError):
        gate.validate_canonical_identity(None)  # type: ignore[arg-type]  # deliberate bad input


def test_real_canonical_still_agrees_with_facts():
    assert gate.validate_canonical_identity(CANON) == []


# ---------------------------------------------------------------------------
# apply.py integration (A, B, E through apply_one / run_queue)
# ---------------------------------------------------------------------------

def _payload(**overrides) -> dict:
    payload = {k: CANON[k] for k in ("name", "phone", "email", "linkedin", "github", "portfolio")}
    payload["company"] = "Ahead"
    payload.update(overrides)
    return payload


def _mock_submitters(monkeypatch) -> dict[str, int]:
    import ats_apply, direct_form, indeed_apply
    calls = {"indeed": 0, "ats": 0, "direct": 0}

    def ok(key):
        def _inner(*a, **kw):
            calls[key] += 1
            return S.ApplyResult(S.SUBMITTED, evidence="mock confirmation page")
        return _inner

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", ok("indeed"))
    monkeypatch.setattr(ats_apply, "run_ats_apply", ok("ats"))
    monkeypatch.setattr(direct_form, "run_direct_apply", ok("direct"))
    return calls


def _seed_job(db, tmp_path, url: str, *, company="Ahead", channel=S.CH_INDEED, letter=CLEAN_LETTER,
              job_board="other", ats_meta=None) -> dict:
    cover = tmp_path / f"{abs(hash(url))}-cover.txt"
    cover.write_text(letter)
    j = {"url": url, "company": company, "title": "Backend Engineer", "description": "python api",
         "job_board": job_board, "location": "Remote", "salary_min": None, "salary_max": None,
         "date_posted": None, "status": S.TAILORED}
    db.upsert_job(j)
    db.update_job(url, {"dedupe_key": db.dedupe_key(company, "Backend Engineer"),
                        "apply_channel": channel, "ats_meta": ats_meta})
    conn = db.get_conn()
    row = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    row["cover_letter_path"] = str(cover)
    return row


def _status(db, url) -> dict:
    conn = db.get_conn()
    row = dict(conn.execute("SELECT status, status_reason FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    return row


@pytest.mark.parametrize("break_gate", ["none", "false", "zero", "tuple", "str", "mixed"])
def test_apply_one_treats_gate_contract_violation_as_infra_error(temp_db, monkeypatch, tmp_path, break_gate):
    """GateContractError (validator returned something other than list[str]) is classified
    infra_error, not a job-data finding: it recurs identically for every job regardless of
    that job's own data, so it must never consume the bounded validation_attempts budget —
    apply.py reverts the attempt and stays TAILORED, repeatable indefinitely."""
    import apply
    calls = _mock_submitters(monkeypatch)

    def broken(job, letter):
        return {"none": None, "false": False, "zero": 0, "tuple": ("x",), "str": "bad",
                "mixed": ["ok", 7]}[break_gate]

    monkeypatch.setattr(gate, "validate_job_submission", broken)
    row = _seed_job(temp_db, tmp_path, f"https://x/broken-{break_gate}")
    result = apply.apply_one(row, CFG, dry_run=False)
    assert result.state == S.GATE_INFRA_ERROR
    assert sum(calls.values()) == 0
    row_after = _status(temp_db, row["url"])
    assert row_after["status"] == S.TAILORED
    assert "gate_infra_error" in row_after["status_reason"]


def test_apply_one_treats_generic_gate_exception_as_bounded_job_data_error(temp_db, monkeypatch, tmp_path):
    """A generic (non-GateConfigError/GateContractError) exception from the gate is THIS
    job's data breaking something unanticipated — classified job_data_error, counted toward
    the bounded validation_attempts budget exactly like a genuine finding, never infra."""
    import apply
    calls = _mock_submitters(monkeypatch)

    def boom(job, letter):
        raise RuntimeError("gate blew up")

    monkeypatch.setattr(gate, "validate_job_submission", boom)
    row = _seed_job(temp_db, tmp_path, "https://x/broken-raises")
    result = apply.apply_one(row, CFG, dry_run=False)
    assert result.state == S.VALIDATION_FAILED
    assert result.meta.get("gate_kind") == "job_data_error"
    assert sum(calls.values()) == 0
    row_after = _status(temp_db, row["url"])
    assert row_after["status"] == S.TAILORED


def test_run_queue_survives_gate_exceptions_and_records_each_job(temp_db, monkeypatch, tmp_path):
    import apply
    calls = _mock_submitters(monkeypatch)

    def boom(job, letter):
        raise RuntimeError("gate blew up")

    monkeypatch.setattr(gate, "validate_job_submission", boom)
    queue = [_seed_job(temp_db, tmp_path, f"https://x/q{i}") for i in range(3)]
    stats = apply.run_queue(queue, CFG, dry_run=True, deadline=1e12)
    assert stats[S.VALIDATION_FAILED] == 3          # transient tag; still the correct bucket key
    assert sum(calls.values()) == 0
    # One occurrence each: persisted status is TAILORED (budget not yet exhausted), never
    # the transient VALIDATION_FAILED tag itself.
    assert all(_status(temp_db, j["url"])["status"] == S.TAILORED for j in queue)


def test_missing_facts_blocks_apply_one(temp_db, monkeypatch, tmp_path, facts_file):
    """profile/facts.md missing is a GateConfigError — an environment/config problem that
    recurs for every job, not this job's data — so it is classified infra_error, not a
    bounded VALIDATION_FAILED finding."""
    import apply
    calls = _mock_submitters(monkeypatch)
    row = _seed_job(temp_db, tmp_path, "https://x/no-facts")
    result = apply.apply_one(row, CFG, dry_run=False)
    assert result.state == S.GATE_INFRA_ERROR and "facts.md" in result.detail
    assert sum(calls.values()) == 0
    assert _status(temp_db, row["url"])["status"] == S.TAILORED


def test_company_mismatch_blocks_apply_one(temp_db, monkeypatch, tmp_path):
    import apply
    calls = _mock_submitters(monkeypatch)
    row = _seed_job(temp_db, tmp_path, "https://x/mismatch", company="Globex")
    result = apply.apply_one(row, CFG, dry_run=False)
    assert result.state == S.VALIDATION_FAILED and "different company" in result.detail
    assert sum(calls.values()) == 0
    assert "different company" in _status(temp_db, row["url"])["status_reason"]


def test_validation_failed_is_terminal_not_retryable(temp_db, monkeypatch, tmp_path):
    """VALIDATION_FAILED is only ever a transient ApplyResult.state tag — never itself a
    persisted jobs.status. 3 calls to apply_one on the same bad-data job: occurrences 1-2
    land on persisted TAILORED (bounded-retry budget remaining), occurrence 3 exhausts the
    budget into terminal MANUAL_REVIEW. VALIDATION_FAILED stays out of RETRYABLE throughout —
    it is governed by its own validation_attempts/MAX_VALIDATION_ATTEMPTS counter, not the
    generic attempts/MAX_ATTEMPTS retry mechanism."""
    import apply
    _mock_submitters(monkeypatch)
    row = _seed_job(temp_db, tmp_path, "https://x/terminal", company="Unknown")
    cover_letter_path = row["cover_letter_path"]
    assert S.VALIDATION_FAILED not in S.RETRYABLE

    for expected_status, expected_validation_attempts in (
        (S.TAILORED, 1), (S.TAILORED, 2), (S.MANUAL_REVIEW, 3)
    ):
        result = apply.apply_one(row, CFG, dry_run=False)
        assert result.state == S.VALIDATION_FAILED
        conn = temp_db.get_conn()
        db_row = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (row["url"],)).fetchone())
        conn.close()
        assert db_row["status"] == expected_status
        assert db_row["validation_attempts"] == expected_validation_attempts
        row = db_row
        row["cover_letter_path"] = cover_letter_path  # not a persisted jobs column; carry forward

    # Exhausted: terminal and human-release-only — not claimable for another automatic attempt.
    assert temp_db.claim_job(row["url"]) is False


# ---------------------------------------------------------------------------
# G. Redirect path (apply.py route()): can resolution change what the gate validated?
# ---------------------------------------------------------------------------

def _spy_gate(monkeypatch) -> list[tuple[str, str]]:
    """Record (company, cover) for every gate invocation."""
    seen: list[tuple[str, str]] = []
    real = gate.validate_job_submission

    def spy(job, letter):
        seen.append((job["company"], letter))
        return real(job, letter)

    monkeypatch.setattr(gate, "validate_job_submission", spy)
    return seen


def test_blocked_job_never_triggers_redirect_resolution(temp_db, monkeypatch, tmp_path):
    import redirect_resolver
    import apply
    _mock_submitters(monkeypatch)
    resolved: list[str] = []
    monkeypatch.setattr(redirect_resolver, "resolve_apply_target",
                        lambda url: resolved.append(url) or {"error": "should not be called"})
    row = _seed_job(temp_db, tmp_path, "https://remotive.com/job/1", company="Unknown",
                    channel="", job_board="remotive")
    result = apply.apply_one(row, CFG, dry_run=False)
    assert result.state == S.VALIDATION_FAILED
    assert resolved == [], "no browser/HTTP resolution may happen for a gate-blocked job"


@pytest.mark.parametrize("resolution", ["ats_meta", "direct", "ats_meta_hostile_company"])
def test_redirect_resolution_cannot_change_gated_company_cover_or_identity(
        temp_db, monkeypatch, tmp_path, resolution):
    """REPRODUCTION ATTEMPT for the claimed post-gate redirect bypass: whatever the resolver
    returns, the company/cover/identity that reach the submitter are exactly what the gate
    validated (the resolver only receives the URL and only writes ats_meta/apply_channel/
    direct_apply_url back onto the job)."""
    import ats_apply, direct_form, redirect_resolver
    import apply
    gate_inputs = _spy_gate(monkeypatch)
    received: dict[str, object] = {}

    def fake_ats(job, cover, resume, shot, dry_run=False, **kw):
        received.update(kind="ats", company=job["company"], cover=cover)
        return S.ApplyResult(S.SUBMITTED, evidence="confirmation")

    def fake_direct(job, cover, resume, shot, dry_run=False, **kw):
        received.update(kind="direct", company=job["company"], cover=cover)
        return S.ApplyResult(S.SUBMITTED, evidence="confirmation")

    monkeypatch.setattr(ats_apply, "run_ats_apply", fake_ats)
    monkeypatch.setattr(direct_form, "run_direct_apply", fake_direct)
    import json
    targets = {
        "ats_meta": {"ats_meta": json.dumps({"ats": "greenhouse", "apply_url": "https://x", "job_id": "1",
                                              "token": "t"}), "final_url": "https://x"},
        "direct": {"error": "unsupported_destination:other.example", "final_url": "https://other.example/apply"},
        "ats_meta_hostile_company": {"ats_meta": json.dumps({
            "ats": "greenhouse", "apply_url": "https://x", "job_id": "1", "token": "globex",
            "company": "Globex", "name": "Globex"}), "final_url": "https://boards.greenhouse.io/globex/jobs/1"},
    }
    seen_urls: list[str] = []
    monkeypatch.setattr(redirect_resolver, "resolve_apply_target",
                        lambda url: seen_urls.append(url) or targets[resolution])
    row = _seed_job(temp_db, tmp_path, "https://remotive.com/job/2", channel="", job_board="remotive")
    result = apply.apply_one(row, CFG, dry_run=False)

    assert result.state == S.SUBMITTED
    assert seen_urls == ["https://remotive.com/job/2"]          # the resolver only ever sees the URL
    assert len(gate_inputs) == 1                                  # gate ran once, before resolution
    assert received["company"] == gate_inputs[0][0] == "Ahead"    # company unchanged by resolution
    assert received["cover"] == gate_inputs[0][1] == CLEAN_LETTER.strip()  # cover unchanged
    assert answers._profile() == CANON                            # identity source unchanged


def test_indeed_external_apply_hop_cannot_change_gated_fields(temp_db, monkeypatch, tmp_path):
    import direct_form, indeed_apply, redirect_resolver
    import apply
    gate_inputs = _spy_gate(monkeypatch)
    received: dict[str, object] = {}
    monkeypatch.setattr(indeed_apply, "run_indeed_apply",
                        lambda *a, **kw: S.ApplyResult(S.UNSUPPORTED_CHANNEL,
                                                       "external apply: https://indeed.example/applystart?jk=1"))
    monkeypatch.setattr(redirect_resolver, "resolve_indeed_external",
                        lambda url: {"error": "unsupported_destination:other.example",
                                     "final_url": "https://other.example/apply"})

    def fake_direct(job, cover, resume, shot, dry_run=False, **kw):
        received.update(company=job["company"], cover=cover)
        return S.ApplyResult(S.SUBMITTED, evidence="confirmation")

    monkeypatch.setattr(direct_form, "run_direct_apply", fake_direct)
    row = _seed_job(temp_db, tmp_path, "https://in.indeed.com/viewjob?jk=1", channel=S.CH_INDEED)
    result = apply.apply_one(row, CFG, dry_run=False)
    assert result.state == S.SUBMITTED
    assert len(gate_inputs) == 1
    assert received == {"company": "Ahead", "cover": CLEAN_LETTER.strip()}


# ---------------------------------------------------------------------------
# H. classify_gate_outcome — ok / finding / infra_error / job_data_error
# ---------------------------------------------------------------------------

def test_classify_gate_outcome_ok_for_empty_findings():
    assert gate.classify_gate_outcome([]) == "ok"


def test_classify_gate_outcome_finding_for_a_genuine_problem():
    assert gate.classify_gate_outcome(["cover letter names a different company"]) == "finding"
    assert gate.classify_gate_outcome(["problem one", "problem two"]) == "finding"


def test_classify_gate_outcome_infra_error_for_gate_config_error(monkeypatch):
    def boom(job, letter):
        raise gate.GateConfigError("profile/facts.md is empty")
    monkeypatch.setattr(gate, "validate_job_submission", boom)
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert gate.classify_gate_outcome(findings) == "infra_error"
    assert findings[0].startswith(gate.GATE_INFRA_PREFIX)


def test_classify_gate_outcome_infra_error_for_gate_contract_error(monkeypatch):
    monkeypatch.setattr(gate, "validate_job_submission", lambda job, letter: None)
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert gate.classify_gate_outcome(findings) == "infra_error"
    assert findings[0].startswith(gate.GATE_INFRA_PREFIX)
    assert "GateContractError" in findings[0]


def test_classify_gate_outcome_job_data_error_for_generic_exception(monkeypatch):
    def boom(job, letter):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(gate, "validate_job_submission", boom)
    findings = gate.run_submission_gate(GOOD_JOB, CLEAN_LETTER)
    assert gate.classify_gate_outcome(findings) == "job_data_error"
    assert findings[0].startswith(gate.GATE_JOB_DATA_PREFIX)


def test_classify_gate_outcome_defaults_unknown_single_findings_to_finding_not_infra():
    """A single-element findings list that doesn't start with either prefix (a genuine,
    ordinary finding that happens to be the only one) must classify as 'finding', never
    accidentally match the infra/job_data prefix branches."""
    assert gate.classify_gate_outcome(["cover letter is empty, missing, or whitespace-only"]) == "finding"


# ---------------------------------------------------------------------------
# I. find_retired_project_mentions — F2 gate-level backstop
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Shade Ledger", "HeatMax", "Carbon Compass"])
def test_find_retired_project_mentions_detects_each_retired_project(name):
    text = f"I previously worked on {name}, a great project."
    assert gate.find_retired_project_mentions(text) == [name]


def test_find_retired_project_mentions_ignores_active_projects():
    text = "I built Neuro-Zenith, AWIS and Hermes, all active projects."
    assert gate.find_retired_project_mentions(text) == []


def test_find_retired_project_mentions_is_case_insensitive_and_word_bounded():
    assert gate.find_retired_project_mentions("i worked on heatmax") == ["HeatMax"]
    # "Shade" alone must not false-positive as "Shade Ledger"
    assert gate.find_retired_project_mentions("the room was in shade all day") == []


@pytest.mark.parametrize("text", [None, ""])
def test_find_retired_project_mentions_handles_blank_input(text):
    assert gate.find_retired_project_mentions(text) == []


def test_validate_cover_letter_rejects_a_retired_project_mention():
    letter = CLEAN_LETTER + "\n\nI previously built Shade Ledger."
    problems = gate.validate_cover_letter(letter, CANON)
    assert any("retired project" in p and "Shade Ledger" in p for p in problems)


# ---------------------------------------------------------------------------
# J. F1 — direct unit-level matrix (conditions 4-7; see tests/test_f1_empty_letter_matrix.py
#    for the full end-to-end matrix across every real submit call site, both pipelines)
# ---------------------------------------------------------------------------

def test_read_cover_letter_maps_missing_or_empty_file_to_blank_string(tmp_path):
    """F1 conditions 1-3: src/apply.py:read_cover_letter converges every file-shaped
    "there is effectively no letter" input onto "" — proven explicitly for each, not
    assumed from reading the source once."""
    import apply
    zero_byte = tmp_path / "zero-byte.txt"
    zero_byte.write_bytes(b"")

    assert apply.read_cover_letter(None) == ""                                   # condition 1
    assert apply.read_cover_letter(str(tmp_path / "never-written.txt")) == ""    # condition 2
    assert apply.read_cover_letter(str(zero_byte)) == ""                         # condition 3


@pytest.mark.parametrize("text,condition", [
    (None, "condition 4: Python None reaching the gate directly (defensive)"),
    ("", "condition 5: empty string"),
    ("   ", "condition 6: whitespace-only"),
    ("\n\n", "condition 7: newline-only"),
])
def test_validate_cover_letter_rejects_every_blank_shaped_text_value(text, condition):
    problems = gate.validate_cover_letter(text, CANON)
    assert problems == ["cover letter is empty, missing, or whitespace-only"], condition
