"""F1 end-to-end matrix: no empty/missing/whitespace-only cover letter may ever reach a
channel submitter, proven across every real submit call site rather than assumed.

Plan's 7 input conditions (happy-dazzling-yeti.md F1 section):
  1. cover_letter_path missing/None entirely
  2. cover_letter_path set but file doesn't exist on disk
  3. file exists, zero bytes
  4. file content is Python None reaching the gate directly (defensive — a future caller bug)
  5. file content is ""
  6. file content is whitespace-only ("   ")
  7. file content is newline-only ("\n\n")

How the 7 conditions map onto the two real pipelines here:

  * Legacy (src/apply.py) always goes through read_cover_letter(path), which itself maps
    conditions 1-3 to "" (see test_read_cover_letter_maps_missing_or_empty_file_to_blank_string
    in test_submission_gate_hardening.py) before the gate ever sees the value — so conditions
    1, 2, 3, 5, 6, 7 are all exercised here as real file-path inputs, end to end, through
    apply.apply_one, across all 3 legacy submit call sites (indeed_apply.run_indeed_apply,
    ats_apply.run_ats_apply, direct_form.run_direct_apply).

  * Engine (src/engine_apply.py) takes `cover_letter` as a literal string parameter, not a
    path — there is no file-path concept to reproduce conditions 1-3 against. Also,
    `cover_letter=None` is a reserved sentinel on every apply_*_via_engine entry point
    ("generate one via _tailor()"), NOT "pass None through to the gate" — so condition 4
    is not reachable via these public entry points at all; it is verified directly against
    submission_gate.validate_cover_letter(None, canonical) in test_submission_gate_hardening.py
    instead (where the plan itself calls it "defensive, a future caller bug", not a real
    call-site path). Conditions 5, 6, 7 (explicit "", "   ", "\n\n" strings) ARE exercised
    here end to end through apply_indeed_via_engine / apply_wwr_via_engine, across all 3
    engine submit call sites (indeed_apply.run_indeed_apply, ats_apply.run_ats_apply,
    direct_form.run_direct_apply).

Every real run_*_apply is stubbed to raise if called — a gate regression here cannot be
silently absorbed and must surface as either a wrong terminal state or an uncaught error.
"""
from __future__ import annotations

import json

import pytest

import states as S

GOOD_COMPANY = "Ahead"


def _raise_if_called(name):
    def _inner(*a, **kw):
        raise AssertionError(f"{name} must never be called for a gate-blocked job")
    return _inner


# ---------------------------------------------------------------------------
# Legacy path — conditions 1, 2, 3, 5, 6, 7 (file-path based) x 3 call sites
# ---------------------------------------------------------------------------

LEGACY_FILE_CONDITIONS = {
    "cond1_path_none": None,
    "cond2_nonexistent_file": "__MISSING__",
    "cond3_zero_byte_file": "",
    "cond5_empty_string_content": "",
    "cond6_whitespace_only": "   ",
    "cond7_newline_only": "\n\n",
}

LEGACY_SITES = {
    "indeed": (S.CH_INDEED, None, None),
    "ats": (S.CH_GREENHOUSE,
            json.dumps({"ats": "greenhouse", "apply_url": "https://x", "job_id": "1", "token": "t"}),
            None),
    "direct": (S.CH_DIRECT, None, "https://employer.example/apply"),
}


def _legacy_seed(db, tmp_path, url, *, channel, ats_meta, direct_apply_url):
    j = {"url": url, "company": GOOD_COMPANY, "title": "Backend Engineer",
         "description": "python api", "job_board": "other", "location": "Remote",
         "salary_min": None, "salary_max": None, "date_posted": None, "status": S.TAILORED}
    db.upsert_job(j)
    db.update_job(url, {"dedupe_key": db.dedupe_key(GOOD_COMPANY, "Backend Engineer"),
                        "apply_channel": channel, "ats_meta": ats_meta})
    conn = db.get_conn()
    row = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    row["direct_apply_url"] = direct_apply_url  # not a persisted jobs column; in-memory only
    return row


def _legacy_cover_letter_path(tmp_path, condition_key, content, url_suffix):
    if condition_key == "cond1_path_none":
        return None
    if condition_key == "cond2_nonexistent_file":
        return str(tmp_path / f"never-written-{url_suffix}.txt")
    path = tmp_path / f"{url_suffix}.txt"
    path.write_text(content)
    return str(path)


@pytest.mark.parametrize("site_key", list(LEGACY_SITES))
@pytest.mark.parametrize("condition_key", list(LEGACY_FILE_CONDITIONS))
def test_legacy_empty_letter_never_reaches_any_submit_call_site(
    temp_db, monkeypatch, tmp_path, condition_key, site_key
):
    import apply
    import indeed_apply, ats_apply, direct_form

    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _raise_if_called("run_indeed_apply"))
    monkeypatch.setattr(ats_apply, "run_ats_apply", _raise_if_called("run_ats_apply"))
    monkeypatch.setattr(direct_form, "run_direct_apply", _raise_if_called("run_direct_apply"))

    channel, ats_meta, direct_apply_url = LEGACY_SITES[site_key]
    url = f"https://x/f1-{site_key}-{condition_key}"
    row = _legacy_seed(temp_db, tmp_path, url, channel=channel, ats_meta=ats_meta,
                       direct_apply_url=direct_apply_url)
    row["cover_letter_path"] = _legacy_cover_letter_path(
        tmp_path, condition_key, LEGACY_FILE_CONDITIONS[condition_key], f"{site_key}-{condition_key}"
    )

    result = apply.apply_one(row, {
        "search": {"stretch_share": 0.3, "stretch_min_score": 7.5, "min_score": 6.5},
        "limits": {"min_delay_seconds": 0, "max_delay_seconds": 0, "total_per_day": 100,
                  "linkedin_per_day": 0, "other_per_day": 100},
        "resumes": {"default": "resumes/resume-fullstack.pdf"},
    }, dry_run=False)

    assert result is not None
    assert result.state == S.VALIDATION_FAILED
    assert "empty, missing, or whitespace-only" in result.detail
    conn = temp_db.get_conn()
    db_row = dict(conn.execute("SELECT status, validation_attempts FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    assert db_row["status"] == S.TAILORED          # one occurrence: budget not yet exhausted
    assert db_row["validation_attempts"] == 1


# ---------------------------------------------------------------------------
# Engine path — conditions 5, 6, 7 (explicit string, not the None sentinel) x 3 call sites
# ---------------------------------------------------------------------------

ENGINE_STRING_CONDITIONS = {
    "cond5_empty_string_content": "",
    "cond6_whitespace_only": "   ",
    "cond7_newline_only": "\n\n",
}

ENGINE_SITES = {
    "indeed": ("indeed", "indeed"),
    "wwr_ats": ("wwr", "ats"),
    "wwr_direct": ("wwr", "direct"),
}

ENABLED_CFG = {"engine": {"enabled": True}}
GH_META = json.dumps({"ats": "greenhouse", "apply_url": "https://job-boards.greenhouse.io/acme/jobs/1"})


def _engine_setup(site_key, make_opportunity, seed_channel, engine_conn, monkeypatch):
    import engine_apply
    import redirect_resolver
    import indeed_apply, ats_apply, direct_form
    from engine import db as enginedb

    channel, kind = ENGINE_SITES[site_key]
    seed_channel(channel)
    opp_id = make_opportunity(f"canon::f1-{site_key}", candidate_channel=channel, company_display=GOOD_COMPANY)
    now = enginedb.now_iso()
    use_inline_ats = kind == "ats"
    url = "https://in.indeed.com/viewjob?jk=f1" if channel == "indeed" \
        else "https://weworkremotely.com/remote-jobs/f1-engineer"
    engine_conn.execute(
        "INSERT INTO source_observations (opportunity_id, source_name, source_url, observed_at, "
        "raw_metadata, observation_status, created_at) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)",
        (opp_id, channel, url, now, GH_META if use_inline_ats else None, now),
    )
    monkeypatch.setattr(
        redirect_resolver, "resolve_apply_target",
        lambda u: {"final_url": "https://acme.example/careers/1", "channel": None, "ats_meta": None,
                   "error": "unsupported_destination:acme.example"},
    )
    monkeypatch.setattr(indeed_apply, "run_indeed_apply", _raise_if_called("run_indeed_apply"))
    monkeypatch.setattr(ats_apply, "run_ats_apply", _raise_if_called("run_ats_apply"))
    monkeypatch.setattr(direct_form, "run_direct_apply", _raise_if_called("run_direct_apply"))

    if channel == "indeed":
        fn = engine_apply.apply_indeed_via_engine
    else:
        fn = engine_apply.apply_wwr_via_engine
    return opp_id, fn


@pytest.mark.parametrize("site_key", list(ENGINE_SITES))
@pytest.mark.parametrize("condition_key", list(ENGINE_STRING_CONDITIONS))
def test_engine_empty_letter_never_reaches_any_submit_call_site(
    site_key, condition_key, make_opportunity, seed_channel, engine_conn, monkeypatch, tmp_path
):
    opp_id, fn = _engine_setup(site_key, make_opportunity, seed_channel, engine_conn, monkeypatch)
    letter = ENGINE_STRING_CONDITIONS[condition_key]

    tr = fn(engine_conn, "w1", letter, "resume.pdf", str(tmp_path), cfg=ENABLED_CFG)

    assert tr is not None
    # One occurrence: bounded-retry release to READY (budget not yet exhausted), never
    # MANUAL_REVIEW from a single gate finding.
    assert tr.new_application_state == "READY"
    attempt = engine_conn.execute(
        "SELECT * FROM application_attempts WHERE opportunity_id = ?", (opp_id,)
    ).fetchone()
    assert attempt["error_class"] == "gate_finding"
    assert attempt["execution_phase"] == "NOT_STARTED"
    assert "empty, missing, or whitespace-only" in (attempt["error_code"] or "")
