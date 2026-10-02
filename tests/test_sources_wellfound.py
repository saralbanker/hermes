"""
test_sources_wellfound.py — Unit tests for the Wellfound discovery source
(IMPLEMENTATION_ROADMAP.md §82). Pure fixture-based: no network call is made anywhere in
this file. The fixture HTML below mirrors the real, logged-out structure verified live
during Phase 8's investigation (plain `requests.get`, ordinary UA, no login, HTTP 200,
`<script type="application/ld+json">` JobPosting block) — recorded here as fixtures rather
than re-fetched live on every test run.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from sources_wellfound import (
    WELLFOUND_DIRECT_APPLY,
    fetch_wellfound_jobs,
    parse_job_links,
    parse_job_posting,
    strip_html,
)


SAMPLE_LISTING_HTML = """
<html><body>
<a href="/jobs/4793767-senior-software-full-stack-engineer">Senior Software Engineer</a>
<a href="/jobs/4436588-finance-operations-manager">Finance Operations Manager</a>
<a href="/jobs/4793767-senior-software-full-stack-engineer">duplicate link, same card re-rendered</a>
<a href="/company/acme/jobs">not a job detail link — company page</a>
</body></html>
"""


def _detail_html(job_posting: dict) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(job_posting)}</script>'
        "</head><body>irrelevant page chrome</body></html>"
    )


DIRECT_APPLY_JOB = {
    "@context": "http://schema.org/",
    "@type": "JobPosting",
    "title": "Finance Operations Manager",
    "hiringOrganization": {"@type": "Organization", "name": "Carbon Arc"},
    "employmentType": "FULL_TIME",
    "directApply": True,
    "datePosted": "2026-10-02T00:21:38Z",
    "jobLocationType": "TELECOMMUTE",
    "jobLocation": [{"@type": "Place", "address": {
        "addressLocality": "Austin", "addressRegion": "Texas", "addressCountry": "United States"}}],
    "baseSalary": {"@type": "MonetaryAmount", "currency": "USD",
                   "value": {"@type": "QuantitativeValue", "unitText": "YEAR",
                             "minValue": 110000.0, "maxValue": 145000.0}},
    "description": "<p>Own the day-to-day finance engine.</p>",
}

INLINE_GREENHOUSE_JOB = {
    "@context": "http://schema.org/",
    "@type": "JobPosting",
    "title": "Senior Software Engineer",
    "hiringOrganization": {"@type": "Organization", "name": "Beta AI"},
    "employmentType": "FULL_TIME",
    "directApply": False,
    "datePosted": "2026-09-30T00:00:00Z",
    "jobLocation": [],
    "description": '<p>Apply directly: <a href="https://boards.greenhouse.io/betaai/jobs/12345">here</a></p>',
}

NO_ROUTE_EVIDENCE_JOB = {
    "@context": "http://schema.org/",
    "@type": "JobPosting",
    "title": "Mystery Role",
    "hiringOrganization": {"@type": "Organization", "name": "Mystery Co"},
    "employmentType": "FULL_TIME",
    "directApply": False,
    "jobLocation": [],
    "description": "<p>No inline ATS link, and directApply is false.</p>",
}


def test_strip_html():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert strip_html(None) == ""
    assert strip_html("") == ""


def test_parse_job_links_dedupes_and_ignores_non_job_links():
    slugs = parse_job_links(SAMPLE_LISTING_HTML)
    assert slugs == ["4793767-senior-software-full-stack-engineer", "4436588-finance-operations-manager"]


def test_parse_job_links_empty_on_no_matches():
    assert parse_job_links("<html><body>nothing here</body></html>") == []
    assert parse_job_links("") == []


def test_parse_job_posting_direct_apply_true_sets_sentinel_ats_meta():
    """The core Phase 8 finding, exercised directly: a directApply:true posting with no
    inline employer ATS link gets tagged with the WELLFOUND_DIRECT_APPLY sentinel and
    ats_meta carrying direct_apply_only=True — never "redirect" (which would imply a real
    external route might exist)."""
    job = parse_job_posting(_detail_html(DIRECT_APPLY_JOB), "https://wellfound.com/jobs/1-x")
    assert job is not None
    assert job["company"] == "Carbon Arc"
    assert job["title"] == "Finance Operations Manager"
    assert job["location"] == "Remote, Austin, Texas, United States"
    assert job["site"] == "wellfound"
    assert job["min_amount"] == 110000.0
    assert job["max_amount"] == 145000.0
    assert job["currency"] == "USD"
    assert job["date_posted"] == "2026-10-02T00:21:38Z"
    assert job["apply_channel"] == WELLFOUND_DIRECT_APPLY
    assert json.loads(job["ats_meta"]) == {"direct_apply_only": True}
    assert "<p>" not in job["description"]


def test_parse_job_posting_inline_greenhouse_link_outranks_direct_apply_flag():
    """An inline, verifiable employer ATS link always wins, regardless of directApply —
    same precedence src/sources_wwr.py's inline detection already uses."""
    job = parse_job_posting(_detail_html(INLINE_GREENHOUSE_JOB), "https://wellfound.com/jobs/2-x")
    assert job is not None
    assert job["apply_channel"] == "greenhouse"
    meta = json.loads(job["ats_meta"])
    assert meta["ats"] == "greenhouse"
    assert meta["token"] == "betaai"


def test_parse_job_posting_no_route_evidence_falls_back_to_generic_redirect():
    """directApply:false and no inline link: not assumed unsupported — handed to the
    generic redirect resolver exactly like a default WWR listing."""
    job = parse_job_posting(_detail_html(NO_ROUTE_EVIDENCE_JOB), "https://wellfound.com/jobs/3-x")
    assert job is not None
    assert job["apply_channel"] == "redirect"
    assert job["ats_meta"] is None


def test_parse_job_posting_remote_without_location_falls_back_to_bare_remote():
    job_posting = {**DIRECT_APPLY_JOB, "jobLocation": []}
    job = parse_job_posting(_detail_html(job_posting), "https://wellfound.com/jobs/4-x")
    assert job["location"] == "Remote"


def test_parse_job_posting_returns_none_without_jobposting_block():
    assert parse_job_posting("<html><body>no JSON-LD here</body></html>", "https://wellfound.com/jobs/5-x") is None
    assert parse_job_posting('<script type="application/ld+json">{"@type": "Organization"}</script>',
                              "https://wellfound.com/jobs/6-x") is None


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


def test_fetch_wellfound_jobs_fetches_listing_then_each_detail_page(monkeypatch):
    monkeypatch.setattr("sources_wellfound.time.sleep", lambda *_: None)  # no real pacing delay in tests

    listing_resp = _mock_response(200, SAMPLE_LISTING_HTML)
    detail1 = _mock_response(200, _detail_html(DIRECT_APPLY_JOB))
    detail2 = _mock_response(200, _detail_html(INLINE_GREENHOUSE_JOB))

    with patch("sources_wellfound.requests.get", side_effect=[listing_resp, detail1, detail2]) as mock_get:
        df = fetch_wellfound_jobs({"search": {"results_wanted": 10}})

    assert len(df) == 2
    assert set(df["apply_channel"]) == {WELLFOUND_DIRECT_APPLY, "greenhouse"}
    assert all(df["site"] == "wellfound")
    # listing fetch + one detail fetch per distinct job link found.
    assert mock_get.call_count == 3


def test_fetch_wellfound_jobs_respects_limit(monkeypatch):
    monkeypatch.setattr("sources_wellfound.time.sleep", lambda *_: None)

    listing_resp = _mock_response(200, SAMPLE_LISTING_HTML)  # 2 distinct links available
    detail1 = _mock_response(200, _detail_html(DIRECT_APPLY_JOB))

    with patch("sources_wellfound.requests.get", side_effect=[listing_resp, detail1]) as mock_get:
        df = fetch_wellfound_jobs({"search": {}}, limit=1)

    assert len(df) == 1
    assert mock_get.call_count == 2  # listing + exactly one detail page, not both


def test_fetch_wellfound_jobs_returns_empty_df_on_listing_failure(monkeypatch):
    monkeypatch.setattr("sources_wellfound.time.sleep", lambda *_: None)
    bad_resp = _mock_response(503)

    with patch("sources_wellfound.requests.get", return_value=bad_resp):
        df = fetch_wellfound_jobs({"search": {"results_wanted": 10}})

    assert df.empty
    assert list(df.columns)  # still has the expected COLUMNS shape, just no rows


def test_fetch_wellfound_jobs_skips_a_failed_detail_page_without_aborting_the_rest(monkeypatch):
    monkeypatch.setattr("sources_wellfound.time.sleep", lambda *_: None)

    listing_resp = _mock_response(200, SAMPLE_LISTING_HTML)
    bad_detail = _mock_response(404)
    good_detail = _mock_response(200, _detail_html(INLINE_GREENHOUSE_JOB))

    with patch("sources_wellfound.requests.get", side_effect=[listing_resp, bad_detail, good_detail]):
        df = fetch_wellfound_jobs({"search": {"results_wanted": 10}})

    assert len(df) == 1
    assert df.iloc[0]["apply_channel"] == "greenhouse"
