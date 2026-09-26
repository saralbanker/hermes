"""
test_sources_new.py — Unit and integration tests for new discovery sources
(We Work Remotely, Arbeitnow) and fast ATS application URL resolution.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from redirect_resolver import ats_from_url, resolve_apply_target, resolve_fast_http
from sources_arbeitnow import (
    ENGINEERING_KEYWORDS,
    fetch_arbeitnow_jobs,
    resolve_apply_target_fast,
    strip_html as strip_arbeitnow_html,
)
from sources_wwr import (
    fetch_wwr_jobs,
    parse_wwr_rss,
    strip_html as strip_wwr_html,
)


SAMPLE_WWR_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>We Work Remotely</title>
    <item>
      <title>Acme Corp: Senior Full Stack Engineer</title>
      <link>https://weworkremotely.com/remote-jobs/acme-corp-senior-full-stack-engineer</link>
      <guid>https://weworkremotely.com/remote-jobs/acme-corp-senior-full-stack-engineer</guid>
      <region>Anywhere in the World</region>
      <pubDate>Fri, 26 Sep 2026 12:00:00 +0000</pubDate>
      <description>&lt;p&gt;We are hiring a Senior Full Stack Engineer.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Beta AI: Python Developer</title>
      <link>https://weworkremotely.com/remote-jobs/beta-ai-python-developer</link>
      <guid>https://weworkremotely.com/remote-jobs/beta-ai-python-developer</guid>
      <region>Worldwide</region>
      <pubDate>Fri, 26 Sep 2026 11:00:00 +0000</pubDate>
      <description>&lt;p&gt;Apply directly at &lt;a href="https://boards.greenhouse.io/betaai/jobs/12345"&gt;link&lt;/a&gt;&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""


def test_parse_wwr_rss():
    jobs = parse_wwr_rss(SAMPLE_WWR_XML)
    assert len(jobs) == 2

    j0 = jobs[0]
    assert j0["company"] == "Acme Corp"
    assert j0["title"] == "Senior Full Stack Engineer"
    assert "Remote, Anywhere in the World" in j0["location"]
    assert j0["site"] == "wwr"
    assert j0["apply_channel"] == "redirect"
    assert j0["ats_meta"] is None
    assert "We are hiring" in j0["description"]

    j1 = jobs[1]
    assert j1["company"] == "Beta AI"
    assert j1["title"] == "Python Developer"
    assert j1["apply_channel"] == "greenhouse"
    assert j1["ats_meta"] is not None
    meta = json.loads(j1["ats_meta"])
    assert meta["ats"] == "greenhouse"
    assert meta["token"] == "betaai"
    assert meta["job_id"] == "12345"


def test_arbeitnow_engineering_keyword_filter():
    assert ENGINEERING_KEYWORDS.search("Senior Software Engineer")
    assert ENGINEERING_KEYWORDS.search("Backend Developer")
    assert ENGINEERING_KEYWORDS.search("AI/ML Research Scientist")
    assert ENGINEERING_KEYWORDS.search("Platform Engineer")
    assert not ENGINEERING_KEYWORDS.search("Sales Account Executive")
    assert not ENGINEERING_KEYWORDS.search("Office Manager")


def test_arbeitnow_fast_resolve():
    with patch("requests.head") as mock_head:
        # Mock 302 redirect to Greenhouse
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {
            "Location": "https://job-boards.greenhouse.io/purestorage/jobs/8232778?utm_source=arbeitnow.com"
        }
        mock_head.return_value = mock_resp

        channel, meta_str = resolve_apply_target_fast("https://www.arbeitnow.com/jobs/companies/purestorage/remote-dev-123")
        assert channel == "greenhouse"
        assert meta_str is not None
        meta = json.loads(meta_str)
        assert meta["ats"] == "greenhouse"
        assert meta["token"] == "purestorage"
        assert meta["job_id"] == "8232778"


def test_redirect_resolver_fast_http_arbeitnow():
    with patch("requests.head") as mock_head:
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {
            "Location": "https://jobs.lever.co/anyscale/a9f97d51-1779-45f8-8bb3-5a0dc0ea92e5"
        }
        mock_head.return_value = mock_resp

        res = resolve_fast_http("https://www.arbeitnow.com/jobs/companies/anyscale/backend-eng-123")
        assert res is not None
        assert res["channel"] == "lever"
        assert res["error"] is None
        meta = json.loads(res["ats_meta"])
        assert meta["token"] == "anyscale"


def test_redirect_resolver_fast_http_early_reject():
    # Early reject hard sign-up walls without launching browser
    res1 = resolve_fast_http("https://remoteok.com/sign-up?user_type=worker")
    assert res1 is not None
    assert "account_required" in res1["error"]

    res2 = resolve_fast_http("https://himalayas.app/signup/talent")
    assert res2 is not None
    assert "account_required" in res2["error"]

    res3 = resolve_fast_http("https://jobicy.com/jobs/12345-dev")
    assert res3 is not None
    assert "account_required" in res3["error"]


def test_discover_registry():
    from discover import CHANNEL_BY_SITE, SCRAPERS
    assert "wwr" in SCRAPERS
    assert "arbeitnow" in SCRAPERS
    assert CHANNEL_BY_SITE.get("wwr") == "redirect"
    assert CHANNEL_BY_SITE.get("arbeitnow") == "redirect"
