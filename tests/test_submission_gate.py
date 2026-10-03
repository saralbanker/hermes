"""Tests for submission_gate.py — the hard pre-submission validation gate — and for its
wiring into apply.py's dispatch choke point in apply_one().

No network, no browser: the channel submitters (indeed_apply.run_indeed_apply,
ats_apply.run_ats_apply, direct_form.run_direct_apply) are monkeypatched in every test
that touches apply.py's dispatch path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import states as S
import submission_gate as gate
from answers import _profile

ROOT = Path(__file__).parent.parent
CANON = _profile()  # the live config.yaml `profile:` block — the single source of truth

GOOD_PHONE = CANON["phone"]            # "+91 9106990136"
BAD_PHONE_KNOWN = "9016990136"         # the historically transposed value
GOOD_NAME = CANON["name"]              # "Saral Banker"
GOOD_EMAIL = CANON["email"]            # "saralbanker1@gmail.com"
GOOD_LINKEDIN = CANON["linkedin"]
GOOD_GITHUB = CANON["github"]
GOOD_PORTFOLIO = CANON["portfolio"]

# A real, clean, un-corrupted cover letter pulled straight from output/tailored/.
CLEAN_LETTER_PATH = ROOT / "output" / "tailored" / "ahead-netsuite-developer-cover.txt"
CLEAN_LETTER = CLEAN_LETTER_PATH.read_text()


def good_payload(**overrides) -> dict:
    payload = {"name": GOOD_NAME, "phone": GOOD_PHONE, "email": GOOD_EMAIL,
               "linkedin": GOOD_LINKEDIN, "github": GOOD_GITHUB, "portfolio": GOOD_PORTFOLIO,
               "company": "Ahead"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Phone
# ---------------------------------------------------------------------------

def test_correct_canonical_phone_passes():
    assert gate.validate_submission(good_payload(), CLEAN_LETTER, CANON) == []


def test_known_transposed_phone_is_rejected():
    problems = gate.validate_submission(good_payload(phone=BAD_PHONE_KNOWN), CLEAN_LETTER, CANON)
    assert any("transposed" in p for p in problems)


def test_other_wrong_phone_is_rejected():
    problems = gate.validate_submission(good_payload(phone="+91 7000000000"), CLEAN_LETTER, CANON)
    assert any("does not match the canonical phone" in p for p in problems)


def test_phone_formatting_differences_do_not_false_positive():
    # same number, different formatting -> normalize_phone must treat them as equal
    assert gate.normalize_phone("+91 9106990136") == gate.normalize_phone("9106990136")
    assert gate.normalize_phone("91-9106-990136") == gate.normalize_phone("09106990136")


def test_transposed_phone_embedded_in_cover_letter_is_rejected():
    corrupted = CLEAN_LETTER + "\n\nCall me at 9016990136."
    problems = gate.validate_cover_letter(corrupted, CANON)
    assert any("transposed" in p for p in problems)


def test_mismatched_phone_embedded_in_cover_letter_is_rejected():
    corrupted = CLEAN_LETTER + "\n\nReach me at +91 8888812345."
    problems = gate.validate_cover_letter(corrupted, CANON)
    assert any("does not match the canonical phone" in p for p in problems)


# ---------------------------------------------------------------------------
# Name
# ---------------------------------------------------------------------------

def test_correct_name_passes():
    assert gate.validate_submission(good_payload(), CLEAN_LETTER, CANON) == []


def test_mismatched_name_is_rejected():
    problems = gate.validate_submission(good_payload(name="John Smith"), CLEAN_LETTER, CANON)
    assert any("name" in p and "does not match" in p for p in problems)


def test_name_match_is_case_insensitive():
    assert gate._validate_text_field(GOOD_NAME.upper(), GOOD_NAME, "name", gate.normalize_name) == []


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def test_correct_email_passes():
    assert gate.validate_submission(good_payload(), CLEAN_LETTER, CANON) == []


def test_mismatched_email_is_rejected():
    problems = gate.validate_submission(good_payload(email="someone@else.com"), CLEAN_LETTER, CANON)
    assert any("email" in p and "does not match" in p for p in problems)


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token", [
    "[Your Name]", "[Company Name]", "[Hiring Manager]", "[Phone Number]", "[Email]",
    "[Date]", "[Something Else Entirely]",
])
def test_bracket_placeholders_are_rejected(token):
    corrupted = CLEAN_LETTER + f"\n\n{token}"
    problems = gate.validate_cover_letter(corrupted, CANON)
    assert any("placeholder" in p for p in problems)


@pytest.mark.parametrize("token", ["{company}", "{devlogic}", "{hiring_manager}"])
def test_curly_placeholders_are_rejected(token):
    corrupted = CLEAN_LETTER + f"\n\n{token}"
    problems = gate.validate_cover_letter(corrupted, CANON)
    assert any("placeholder" in p for p in problems)


def test_real_clean_cover_letter_passes():
    assert gate.validate_cover_letter(CLEAN_LETTER, CANON) == []


def test_real_corrupted_cover_letter_sample_is_rejected():
    # a real historically-observed corruption pattern, pulled from output/tailored/
    corrupted_path = ROOT / "output" / "tailored" / "appsflyer-backend-engineer-cover.txt"
    text = corrupted_path.read_text()
    problems = gate.validate_cover_letter(text, CANON)
    assert any("placeholder" in p for p in problems)


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_company", ["Unknown", "unknown", "N/A", "n/a", None, "", "   "])
def test_bad_company_values_are_rejected(bad_company):
    problems = gate.validate_company(bad_company)
    assert problems


def test_real_company_name_passes():
    assert gate.validate_company("Ahead") == []


def test_candidate_name_used_as_company_is_rejected():
    letter = f"I'm applying for the Backend Engineer role at {GOOD_NAME}. I like owning systems end to end."
    problems = gate.validate_cover_letter(letter, CANON)
    assert any("candidate's own name" in p for p in problems)


def test_generic_company_reference_in_letter_is_rejected():
    letter = "I'm applying for the Backend Engineer role at Unknown. I like owning systems end to end."
    problems = gate.validate_cover_letter(letter, CANON)
    assert any("malformed/generic company reference" in p for p in problems)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def test_correct_links_pass():
    assert gate.validate_links(good_payload(), CANON) == []


def test_mismatched_linkedin_is_rejected():
    problems = gate.validate_links(good_payload(linkedin="https://www.linkedin.com/in/someoneelse"), CANON)
    assert any("linkedin" in p for p in problems)


def test_mismatched_github_is_rejected():
    problems = gate.validate_links(good_payload(github="github.com/someoneelse"), CANON)
    assert any("github" in p for p in problems)


def test_links_are_scheme_and_www_insensitive():
    assert gate.normalize_link("https://www.linkedin.com/in/saralbanker") == \
        gate.normalize_link("linkedin.com/in/saralbanker/")


# ---------------------------------------------------------------------------
# validate_canonical_identity — independent cross-check of config.yaml's `profile:`
# block against profile/facts.md's `## Contact` section (parsed separately). Catches
# config.yaml drifting from the repo's declared source of truth, which a payload-vs-
# canonical check alone cannot: at the real call site the payload IS built from
# canonical, so it can never disagree with itself.
# ---------------------------------------------------------------------------

def test_current_config_yaml_agrees_with_facts_md():
    """The real, current config.yaml profile and profile/facts.md Contact section agree
    today — the cross-check must not false-positive on the repo's actual state."""
    assert gate.validate_canonical_identity(CANON) == []


def test_facts_contact_parser_extracts_expected_fields():
    facts = gate._load_facts_contact()
    assert facts["name"] == "Saral Banker"
    assert facts["phone"] == "+91 9106990136"
    assert facts["email"] == "saralbanker1@gmail.com"
    assert facts["github"] == "github.com/saralbanker"
    assert facts["linkedin"] == "linkedin.com/in/saralbanker"
    assert facts["portfolio"] == "orvion-co.vercel.app"


def test_config_yaml_phone_drifted_from_facts_md_is_rejected():
    """Simulates the original incident: config.yaml's phone field gets hand-edited to a
    *different* wrong value (not the specific known-bad constant, which the payload-level
    check happens to catch unconditionally — this proves the general drift case, not just
    that one hardcoded value). A payload built FROM this corrupted canonical dict would
    trivially agree with itself, so this must be caught by the independent facts.md
    cross-check, not by the payload-vs-canonical checks."""
    drifted_phone = "+91 9999999999"
    corrupted_canonical = dict(CANON, phone=drifted_phone)
    problems = gate.validate_canonical_identity(corrupted_canonical)
    assert problems
    assert any("does not match profile/facts.md" in p for p in problems)
    # a payload built entirely from the corrupted canonical agrees with itself, so
    # validate_submission alone (payload-vs-canonical only) does NOT catch the drift —
    # proving the exact gap this independent cross-check closes
    corrupted_payload = good_payload(phone=corrupted_canonical["phone"])
    assert gate.validate_submission(corrupted_payload, CLEAN_LETTER, corrupted_canonical) == []


def test_config_yaml_name_mismatch_vs_facts_md_is_rejected():
    corrupted_canonical = dict(CANON, name="Someone Else")
    problems = gate.validate_canonical_identity(corrupted_canonical)
    assert any("name" in p and "does not match profile/facts.md" in p for p in problems)


def test_config_yaml_github_mismatch_vs_facts_md_is_rejected():
    corrupted_canonical = dict(CANON, github="github.com/impostor")
    problems = gate.validate_canonical_identity(corrupted_canonical)
    assert any("github" in p and "does not match profile/facts.md" in p for p in problems)


def test_drifted_canonical_blocks_every_job_via_validate_job_submission(monkeypatch):
    """If config.yaml itself has drifted, validate_job_submission must block ANY job —
    even one with an otherwise-perfectly-clean company/cover-letter — because every
    job's payload is built from the same corrupted canonical dict."""
    import answers
    corrupted = dict(CANON, phone=BAD_PHONE_KNOWN)
    monkeypatch.setattr(answers, "_profile", lambda: corrupted)
    problems = gate.validate_job_submission({"company": "Ahead"}, CLEAN_LETTER)
    assert problems
    assert any("corrupted" in p for p in problems)


# ---------------------------------------------------------------------------
# validate_job_submission — the apply.py-facing wrapper, loading canonical the same
# way answers.py does (no second copy of the identity values).
# ---------------------------------------------------------------------------

def test_validate_job_submission_passes_for_clean_job():
    job = {"company": "Ahead"}
    assert gate.validate_job_submission(job, CLEAN_LETTER) == []


def test_validate_job_submission_blocks_unknown_company():
    job = {"company": "Unknown"}
    problems = gate.validate_job_submission(job, CLEAN_LETTER)
    assert problems and any("placeholder value" in p for p in problems)


# ---------------------------------------------------------------------------
# Integration: apply.py's actual dispatch path, through apply_one(), with all three
# channel submitters monkeypatched. Proves the gate sits on the one choke point every
# submission path goes through, not just that the gate function itself returns the
# right boolean in isolation.
# ---------------------------------------------------------------------------

CFG = {"search": {"stretch_share": 0.3, "stretch_min_score": 7.5, "min_score": 6.5},
       "limits": {"min_delay_seconds": 0, "max_delay_seconds": 0, "total_per_day": 100,
                  "linkedin_per_day": 0, "other_per_day": 100},
       "resumes": {"default": "resumes/resume-fullstack.pdf"}}


def _seed(db, j, status=S.TAILORED):
    db.upsert_job({**j, "location": "Remote", "salary_min": None, "salary_max": None,
                   "date_posted": None, "status": status})
    db.update_job(j["url"], {"dedupe_key": db.dedupe_key(j["company"], j["title"]),
                             "cover_letter_path": j.get("cover_letter_path"),
                             "apply_channel": j.get("apply_channel")})


def _row(db, url):
    conn = db.get_conn()
    r = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    return r


@pytest.fixture
def cover_letter_files(tmp_path):
    clean = tmp_path / "clean-cover.txt"
    clean.write_text(CLEAN_LETTER)
    return {"clean": clean}


def _mock_submitters(monkeypatch):
    """Monkeypatch every channel submitter's entry point and return call-count trackers."""
    import indeed_apply, ats_apply, direct_form
    calls = {"indeed": 0, "ats": 0, "direct": 0}

    def _ok(key):
        def _inner(*a, **kw):
            calls[key] += 1
            return S.ApplyResult(S.SUBMITTED, evidence="mock confirmation page")
        return _inner

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _ok("indeed"))
    monkeypatch.setattr(ats_apply, "run_ats_apply", _ok("ats"))
    monkeypatch.setattr(direct_form, "run_direct_apply", _ok("direct"))
    return calls


@pytest.mark.parametrize("channel", [S.CH_INDEED, S.CH_GREENHOUSE, S.CH_DIRECT])
def test_bad_job_never_reaches_any_channel_submitter(temp_db, monkeypatch, tmp_path, channel):
    """company='Unknown' must block dispatch to indeed_apply / ats_apply / direct_form alike."""
    import apply
    calls = _mock_submitters(monkeypatch)
    cover_path = tmp_path / "bad-cover.txt"
    cover_path.write_text(CLEAN_LETTER)
    ats_meta = ('{"ats": "greenhouse", "apply_url": "https://x", "job_id": "1", "token": "t"}'
                if channel == S.CH_GREENHOUSE else None)
    j = {"url": f"https://x/bad-{channel}", "company": "Unknown", "title": "Backend Engineer",
         "description": "python api", "job_board": "other", "apply_channel": channel,
         "ats_meta": ats_meta, "direct_apply_url": "https://employer.example/apply",
         "cover_letter_path": str(cover_path.relative_to(ROOT)) if cover_path.is_relative_to(ROOT)
         else str(cover_path)}
    _seed(temp_db, j)
    row = dict(_row(temp_db, j["url"]))
    row["cover_letter_path"] = str(cover_path)  # absolute path, read_cover_letter does ROOT / rel_path
    result = apply.apply_one(row, CFG, dry_run=False)
    assert sum(calls.values()) == 0, "a blocked job must never reach any channel submitter"
    assert result.state == S.VALIDATION_FAILED
    assert _row(temp_db, j["url"])["status"] == S.VALIDATION_FAILED


@pytest.mark.parametrize("channel,call_key", [
    (S.CH_INDEED, "indeed"), (S.CH_GREENHOUSE, "ats"), (S.CH_DIRECT, "direct")])
def test_clean_job_reaches_its_channel_submitter(temp_db, monkeypatch, tmp_path, channel, call_key):
    """All-clean fields must pass the gate and reach the right submitter exactly once."""
    import apply
    calls = _mock_submitters(monkeypatch)
    cover_path = tmp_path / "clean-cover.txt"
    cover_path.write_text(CLEAN_LETTER)
    ats_meta = ('{"ats": "greenhouse", "apply_url": "https://x", "job_id": "1", "token": "t"}'
                if channel == S.CH_GREENHOUSE else None)
    j = {"url": f"https://x/clean-{channel}", "company": "Ahead", "title": "Backend Engineer",
         "description": "python api", "job_board": "other", "apply_channel": channel,
         "ats_meta": ats_meta, "direct_apply_url": "https://employer.example/apply",
         "cover_letter_path": None}
    _seed(temp_db, j)
    row = dict(_row(temp_db, j["url"]))
    row["cover_letter_path"] = str(cover_path)
    result = apply.apply_one(row, CFG, dry_run=False)
    assert calls[call_key] == 1, f"a clean job must reach the {call_key} submitter exactly once"
    assert sum(calls.values()) == 1
    assert result.state == S.SUBMITTED
    assert _row(temp_db, j["url"])["status"] == S.SUBMITTED


def test_validation_failed_job_never_hits_network_and_is_not_retried_as_submitted(temp_db, monkeypatch, tmp_path):
    """Confirms: no network/browser call for a blocked job (no channel submitter ran),
    and the block is terminal (not silently retried into a submitted state)."""
    import apply
    calls = _mock_submitters(monkeypatch)
    cover_path = tmp_path / "bad-cover.txt"
    cover_path.write_text(CLEAN_LETTER + "\n\n[Your Name]")
    j = {"url": "https://x/blocked-1", "company": "Ahead", "title": "Backend Engineer",
         "description": "python api", "job_board": "indeed", "apply_channel": S.CH_INDEED,
         "ats_meta": None, "cover_letter_path": None}
    _seed(temp_db, j)
    row = dict(_row(temp_db, j["url"]))
    row["cover_letter_path"] = str(cover_path)
    result = apply.apply_one(row, CFG, dry_run=False)
    assert calls["indeed"] == 0
    assert result.state == S.VALIDATION_FAILED
    final = _row(temp_db, j["url"])
    assert final["status"] == S.VALIDATION_FAILED
    assert final["status_reason"] and "placeholder" in final["status_reason"]
