"""Offline tests for apply.py's redirect/channel routing: _apply_resolved_target (the
shared tail for both aggregator redirects and Indeed's own external-apply hop),
_follow_redirect, _follow_indeed_external, and route()'s Indeed -> direct/ATS handoff.
No network, no browser — redirect_resolver and the appliers are all monkeypatched.
"""
from __future__ import annotations

import json

import apply
import states as S


def job(**overrides):
    base = {"url": "https://in.indeed.com/viewjob?jk=abc123", "company": "Acme",
            "title": "Backend Engineer", "description": "python api", "location": "Remote"}
    base.update(overrides)
    return base


def _no_op_update_job(monkeypatch):
    calls = []
    monkeypatch.setattr(apply, "update_job", lambda url, fields: calls.append((url, fields)))
    return calls


# ---------------------------------------------------------------------------
# _apply_resolved_target — shared tail
# ---------------------------------------------------------------------------

def test_apply_resolved_target_sets_ats_channel_on_match(monkeypatch):
    calls = _no_op_update_job(monkeypatch)
    meta = json.dumps({"ats": "greenhouse", "token": "acme", "job_id": "1",
                       "apply_url": "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=1"})
    j = job()
    result = apply._apply_resolved_target(j, {"final_url": "x", "ats_meta": meta, "error": None}, "redirect")
    assert result is None
    assert j["apply_channel"] == "greenhouse"
    assert calls and calls[0][1]["apply_channel"] == "greenhouse"


def test_apply_resolved_target_hands_off_unrecognized_destination_to_direct(monkeypatch):
    _no_op_update_job(monkeypatch)
    j = job()
    target = {"final_url": "https://careers.acme.com/apply/123", "ats_meta": None,
              "error": "unsupported_destination:careers.acme.com"}
    result = apply._apply_resolved_target(j, target, "redirect")
    assert result is None
    assert j["apply_channel"] == S.CH_DIRECT
    assert j["direct_apply_url"] == "https://careers.acme.com/apply/123"
    # persisted so a retry doesn't lose the resolved URL
    assert json.loads(j["ats_meta"])["direct_apply_url"] == "https://careers.acme.com/apply/123"


def test_apply_resolved_target_never_hands_account_wall_to_direct(monkeypatch):
    _no_op_update_job(monkeypatch)
    j = job()
    target = {"final_url": "https://himalayas.app/signup/talent?redirect=x", "ats_meta": None,
              "error": "account_required:himalayas.app requires creating an account to apply"}
    result = apply._apply_resolved_target(j, target, "redirect")
    assert result is not None
    assert result.state == S.UNSUPPORTED_CHANNEL
    assert j.get("apply_channel") != S.CH_DIRECT


def test_apply_resolved_target_never_hands_sponsored_link_to_direct(monkeypatch):
    _no_op_update_job(monkeypatch)
    j = job()
    target = {"final_url": "https://aiapply.co/?utm_source=x", "ats_meta": None,
              "error": "sponsored_link:aiapply.co (tracked link, not a job application)"}
    result = apply._apply_resolved_target(j, target, "redirect")
    assert result.state == S.UNSUPPORTED_CHANNEL
    assert j.get("apply_channel") != S.CH_DIRECT


def test_apply_resolved_target_network_error_is_retryable(monkeypatch):
    _no_op_update_job(monkeypatch)
    j = job()
    target = {"final_url": None, "ats_meta": None,
              "error": "redirect_browser_error:TimeoutError: timed out"}
    result = apply._apply_resolved_target(j, target, "indeed external apply")
    assert result.state == S.NETWORK_ERROR
    assert result.detail.startswith("indeed external apply:")


# ---------------------------------------------------------------------------
# _follow_indeed_external
# ---------------------------------------------------------------------------

def test_follow_indeed_external_resolves_to_ats(monkeypatch):
    _no_op_update_job(monkeypatch)
    meta = json.dumps({"ats": "lever", "token": "acme", "job_id": "x",
                       "apply_url": "https://jobs.lever.co/acme/x/apply"})
    import redirect_resolver
    monkeypatch.setattr(redirect_resolver, "resolve_indeed_external",
                        lambda url: {"final_url": "https://jobs.lever.co/acme/x", "ats_meta": meta, "error": None})
    j = job()
    result = apply._follow_indeed_external(j, "https://in.indeed.com/applystart?jk=abc123")
    assert result is None
    assert j["apply_channel"] == "lever"


def test_follow_indeed_external_falls_back_to_direct_for_unknown_ats(monkeypatch):
    _no_op_update_job(monkeypatch)
    import redirect_resolver
    monkeypatch.setattr(redirect_resolver, "resolve_indeed_external", lambda url: {
        "final_url": "https://careers.someco.com/job/1", "ats_meta": None,
        "error": "unsupported_destination:careers.someco.com"})
    j = job()
    result = apply._follow_indeed_external(j, "https://in.indeed.com/applystart?jk=abc123")
    assert result is None
    assert j["apply_channel"] == S.CH_DIRECT
    assert j["direct_apply_url"] == "https://careers.someco.com/job/1"


# ---------------------------------------------------------------------------
# route() — Indeed's "external apply" result triggers the hop, everything else doesn't
# ---------------------------------------------------------------------------

def test_route_follows_indeed_external_apply_to_direct(monkeypatch):
    _no_op_update_job(monkeypatch)
    import indeed_apply
    monkeypatch.setattr(indeed_apply, "run_indeed_apply", lambda *a, **kw: S.ApplyResult(
        S.UNSUPPORTED_CHANNEL, "external apply: https://in.indeed.com/applystart?jk=abc123"))
    monkeypatch.setattr(apply, "_follow_indeed_external", lambda j, url: (
        j.update(apply_channel=S.CH_DIRECT, direct_apply_url="https://careers.someco.com/job/1") or None))
    import direct_form
    monkeypatch.setattr(direct_form, "run_direct_apply",
                        lambda *a, **kw: S.ApplyResult(S.DRY_RUN_OK, "filled"))
    result = apply.route(job(apply_channel=S.CH_INDEED), "cover", "resume.pdf", "shot.png", dry_run=True)
    assert result.state == S.DRY_RUN_OK


def test_route_returns_indeed_result_unchanged_when_not_external_apply(monkeypatch):
    import indeed_apply
    monkeypatch.setattr(indeed_apply, "run_indeed_apply",
                        lambda *a, **kw: S.ApplyResult(S.FORM_CHANGED, "unanswerable: Pronouns"))
    result = apply.route(job(apply_channel=S.CH_INDEED), "cover", "resume.pdf", "shot.png", dry_run=True)
    assert result.state == S.FORM_CHANGED
    assert result.detail == "unanswerable: Pronouns"


def test_resolve_channel_recognizes_direct_apply_url_in_ats_meta():
    j = {"ats_meta": json.dumps({"direct_apply_url": "https://company.com/apply"})}
    assert apply.resolve_channel(j) == S.CH_DIRECT

