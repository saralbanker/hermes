"""State machine, core/stretch allocation, dedupe, claim and cap behaviour of apply.py."""
from __future__ import annotations

import threading

import pytest

import states as S

CFG = {"search": {"stretch_share": 0.3, "stretch_min_score": 7.5, "min_score": 6.5},
       "limits": {"min_delay_seconds": 0, "max_delay_seconds": 0, "total_per_day": 100,
                  "linkedin_per_day": 0, "other_per_day": 100},
       "resumes": {"default": "resumes/resume-fullstack.pdf"}}


def job(i, tier=S.CORE, score=8.0, title="Backend Engineer", company=None, **kw):
    return {"url": f"https://x/{i}", "company": company or f"Co{i}", "title": title,
            "description": "python api", "score": score, "tier": tier, "job_board": "indeed", **kw}


def test_queue_split_is_about_70_30():
    import apply
    jobs = [job(i) for i in range(100)] + [job(100 + i, S.STRETCH) for i in range(100)]
    q = apply.build_queue(jobs, CFG, remaining=100, done={})
    stretch = sum(j["tier"] == S.STRETCH for j in q)
    assert len(q) == 100 and 28 <= stretch <= 32


def test_queue_does_not_pad_with_stretch_when_core_is_short():
    import apply
    jobs = [job(i) for i in range(5)] + [job(100 + i, S.STRETCH) for i in range(50)]
    q = apply.build_queue(jobs, CFG, remaining=100, done={})
    assert sum(j["tier"] == S.STRETCH for j in q) <= 17  # ≈30% of the 55 planned, not 95


def test_queue_respects_already_submitted_stretch_today():
    import apply
    jobs = [job(i) for i in range(10)] + [job(100 + i, S.STRETCH) for i in range(10)]
    q = apply.build_queue(jobs, CFG, remaining=10, done={S.CORE: 0, S.STRETCH: 9})
    assert all(j["tier"] == S.CORE for j in q)


def test_low_scoring_stretch_is_never_queued():
    import apply
    q = apply.build_queue([job(1, S.STRETCH, score=7.0)], CFG, remaining=10, done={})
    assert q == []


def test_submitted_requires_evidence():
    with pytest.raises(ValueError):
        S.ApplyResult(S.SUBMITTED)
    with pytest.raises(ValueError):
        S.ApplyResult("clicked")


def _seed(db, j, status=S.TAILORED):
    db.upsert_job({**j, "location": "Remote", "salary_min": None, "salary_max": None,
                   "date_posted": None, "status": status})
    db.update_job(j["url"], {"dedupe_key": db.dedupe_key(j["company"], j["title"]), "tier": j["tier"]})


def _row(db, url):
    conn = db.get_conn()
    r = dict(conn.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone())
    conn.close()
    return r


def test_transitions(temp_db, monkeypatch):
    import apply
    j = job(1)
    _seed(temp_db, j)
    outcomes = iter([S.ApplyResult(S.NETWORK_ERROR, "dns"),
                     S.ApplyResult(S.SUBMITTED, evidence="Application submitted")])
    monkeypatch.setattr(apply, "route", lambda *a, **k: next(outcomes))
    apply.apply_one(dict(_row(temp_db, j["url"])), CFG, dry_run=False)
    assert _row(temp_db, j["url"])["status"] == S.TAILORED  # retryable → back in queue
    apply.apply_one(dict(_row(temp_db, j["url"])), CFG, dry_run=False)
    row = _row(temp_db, j["url"])
    assert row["status"] == S.SUBMITTED and row["submission_evidence"] and row["attempts"] == 2
    assert temp_db.get_daily_counts()["total_count"] == 1


def test_unconfirmed_click_is_not_submitted_or_counted(temp_db, monkeypatch):
    import apply
    j = job(2)
    _seed(temp_db, j)
    monkeypatch.setattr(apply, "route", lambda *a, **k: S.ApplyResult(S.SUBMISSION_UNCONFIRMED, "no page"))
    apply.apply_one(dict(_row(temp_db, j["url"])), CFG, dry_run=False)
    assert _row(temp_db, j["url"])["status"] == S.SUBMISSION_UNCONFIRMED
    assert temp_db.get_daily_counts()["total_count"] == 0


def test_retry_limit_makes_failure_terminal(temp_db, monkeypatch):
    import apply
    j = job(3)
    _seed(temp_db, j)
    monkeypatch.setattr(apply, "route", lambda *a, **k: S.ApplyResult(S.FAILED, "boom"))
    for _ in range(S.MAX_ATTEMPTS):
        apply.apply_one(dict(_row(temp_db, j["url"])), CFG, dry_run=False)
    assert _row(temp_db, j["url"])["status"] == S.FAILED


def test_applier_exception_is_recorded_not_raised(temp_db, monkeypatch):
    import apply
    j = job(4)
    _seed(temp_db, j)
    def boom(*a, **k):
        raise RuntimeError("chrome crashed")
    monkeypatch.setattr(apply, "route", boom)
    res = apply.apply_one(dict(_row(temp_db, j["url"])), CFG, dry_run=False)
    assert res.state == S.FAILED and "chrome crashed" in res.detail


def test_dry_run_leaves_job_queued_and_uncounted(temp_db, monkeypatch):
    import apply
    j = job(5)
    _seed(temp_db, j)
    monkeypatch.setattr(apply, "route", lambda *a, **k: S.ApplyResult(S.DRY_RUN_OK, "filled"))
    apply.apply_one(dict(_row(temp_db, j["url"])), CFG, dry_run=True)
    row = _row(temp_db, j["url"])
    assert row["status"] == S.TAILORED and row["attempts"] == 0
    assert temp_db.get_daily_counts()["total_count"] == 0


def test_same_role_on_two_boards_is_applied_once(temp_db, monkeypatch):
    import apply
    a = job(6, company="Acme Inc.", title="Backend Engineer")
    b = job(7, company="ACME", title="Backend Engineer (Remote)", job_board="remotive")
    _seed(temp_db, a); _seed(temp_db, b)
    monkeypatch.setattr(apply, "route", lambda *a_, **k: S.ApplyResult(S.SUBMITTED, evidence="ok"))
    apply.apply_one(dict(_row(temp_db, a["url"])), CFG, dry_run=False)
    assert apply.apply_one(dict(_row(temp_db, b["url"])), CFG, dry_run=False) is None
    assert _row(temp_db, b["url"])["status"] == S.SKIPPED


def test_claim_is_atomic_under_concurrency(temp_db):
    j = job(8)
    _seed(temp_db, j)
    wins = []
    threads = [threading.Thread(target=lambda: wins.append(temp_db.claim_job(j["url"]))) for _ in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert wins.count(True) == 1


def test_cap_stops_the_queue(temp_db, monkeypatch):
    import apply
    for i in range(10, 15):
        _seed(temp_db, job(i))
    cfg = {**CFG, "limits": {**CFG["limits"], "total_per_day": 2}}
    monkeypatch.setattr("cap_enforcer.load_limits", lambda: cfg["limits"])
    monkeypatch.setattr(apply, "route", lambda *a, **k: S.ApplyResult(S.SUBMITTED, evidence="ok"))
    queue = [dict(_row(temp_db, f"https://x/{i}")) for i in range(10, 15)]
    apply.run_queue(queue, cfg, dry_run=False, deadline=1e12)
    assert temp_db.get_daily_counts()["total_count"] == 2


def test_login_required_pauses_channel(temp_db, monkeypatch):
    import apply
    for i in range(20, 24):
        _seed(temp_db, job(i))
    calls = []
    def fake(job_, *a, **k):
        calls.append(job_["url"])
        return S.ApplyResult(S.LOGIN_REQUIRED, "expired")
    monkeypatch.setattr(apply, "route", fake)
    monkeypatch.setattr(apply, "_notify_once", lambda *a: None)
    queue = [dict(_row(temp_db, f"https://x/{i}")) for i in range(20, 24)]
    apply.run_queue(queue, CFG, dry_run=False, deadline=1e12)
    assert len(calls) == 1


def test_collapse_duplicates_keeps_most_advanced(temp_db):
    a, b, c = job(30, company="Smart", title="Founding Engineer"), job(31, company="Smart", title="Founding Engineer"), job(32, company="Smart", title="Founding Engineer")
    _seed(temp_db, a, status=S.SCORED); _seed(temp_db, b, status=S.TAILORED); _seed(temp_db, c, status=S.DISCOVERED)
    assert temp_db.collapse_duplicates() == 2
    assert _row(temp_db, b["url"])["status"] == S.TAILORED
    assert {_row(temp_db, x["url"])["status"] for x in (a, c)} == {S.SKIPPED}


def test_channel_breaker_pauses_after_repeated_antibot_blocks():
    import apply
    breaker = apply.ChannelBreaker()
    hit = S.ApplyResult(S.BLOCKED_ANTIBOT, "bot-risk check rejected the submission: spam")
    breaker.observe("ashby", hit)
    assert "ashby" not in breaker.blocked          # one hit could be a fluke
    breaker.observe("ashby", hit)
    assert breaker.blocked["ashby"] == "repeated_antibot_block"


def test_channel_breaker_antibot_counter_is_independent_per_channel():
    import apply
    breaker = apply.ChannelBreaker()
    hit = S.ApplyResult(S.BLOCKED_ANTIBOT, "bot-risk check rejected the submission: spam")
    breaker.observe("ashby", hit)
    breaker.observe("greenhouse", hit)
    assert not breaker.blocked


def test_crash_leftover_applying_rows_are_requeued(temp_db):
    import apply
    j = job(40)
    _seed(temp_db, j)
    assert temp_db.claim_job(j["url"])            # simulated run claims, then "crashes"
    assert apply.reset_stuck_applying(90) == 0    # standalone apply.py: a fresh claim is left alone
    assert apply.reset_stuck_applying(0) == 1     # under the run lock: nobody else can be applying
    assert _row(temp_db, j["url"])["status"] == S.TAILORED


def test_crash_leftover_applying_rows_exceeding_max_attempts_are_failed(temp_db):
    import apply
    j = job(41)
    _seed(temp_db, j)
    # Set attempts to MAX_ATTEMPTS and simulate crash while in 'applying'
    temp_db.update_job(j["url"], {"status": "applying", "attempts": S.MAX_ATTEMPTS})
    assert apply.reset_stuck_applying(0) == 0  # not requeued to tailored
    row = _row(temp_db, j["url"])
    assert row["status"] == S.FAILED
    assert "exceeded MAX_ATTEMPTS" in row["status_reason"]


def test_claim_job_rejects_when_attempts_reach_max(temp_db):
    j = job(42)
    _seed(temp_db, j)
    temp_db.update_job(j["url"], {"attempts": S.MAX_ATTEMPTS})
    # Cannot claim a job that has already reached MAX_ATTEMPTS
    assert not temp_db.claim_job(j["url"], max_attempts=S.MAX_ATTEMPTS)


def test_build_queue_excludes_jobs_with_max_attempts():
    import apply
    jobs = [job(1, attempts=0), job(2, attempts=S.MAX_ATTEMPTS), job(3, attempts=S.MAX_ATTEMPTS + 1)]
    q = apply.build_queue(jobs, CFG, remaining=10, done={})
    assert len(q) == 1
    assert q[0]["url"] == "https://x/1"

