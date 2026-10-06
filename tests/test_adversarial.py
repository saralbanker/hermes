"""
Adversarial tests for Hermes: find inputs where truthfulness fails.

Candidate facts (from profile/facts.md):
- Diploma (no bachelor's/master's)
- ~1 year paid professional experience
- ~4 years hands-on development
- Skills: TypeScript, JavaScript, Python, Go, SQL, React, Node.js, FastAPI, PostgreSQL, etc.
- DOES NOT have (claim): AWS, GCP, Azure, Kubernetes, Java/Spring, .NET, PHP, iOS, ML training
- But DOES mention in skills section: Java (academic), Kotlin (academic)
- Location: Shahibaug, Ahmedabad, India
- Authorized to work in India; needs sponsorship elsewhere
- Available immediately
- Will not relocate
- Open to remote; on-site/hybrid within 20 km (10 km for night shift)
- Salary floor: ₹25k/month India, ₹30k/month global (converted from USD)
"""
import re
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
import yaml

# Ensure src/ is in path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import answers
import filters
import geo


@pytest.fixture
def cfg():
    """Load config.yaml"""
    return yaml.safe_load(open(Path(__file__).parent.parent / "config.yaml"))


@pytest.fixture
def facts_text():
    """Load profile/facts.md"""
    return open(Path(__file__).parent.parent / "profile/facts.md").read()


def mock_no_llm():
    """Monkeypatch to disable LLM fallback (raise ConnectionError on any chat/requests.post)"""
    import requests

    def mock_post(*args, **kwargs):
        raise requests.ConnectionError("Network disabled for test")

    return patch("requests.post", side_effect=mock_post)


# =============================================================================
# answers.py tests: rule_answer() and answer_question()
# =============================================================================

class TestAnswersRuleMatching:
    """Test rule_answer for substring false-positives and logic bugs"""

    def test_academic_only_java_should_return_zero(self, facts_text):
        """Java is listed as (academic only) in facts. Professional Java question should return 0."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of java experience")
            # Facts say Java is academic-only, not professional. Should be 0.
            assert result == "0", f"Java (academic-only) returned {result}, expected 0"

    def test_academic_only_kotlin_should_return_zero(self, facts_text):
        """Kotlin is listed as (academic Android project). Professional Kotlin question should return 0."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of kotlin experience")
            # Facts say Kotlin is academic-only. Should be 0.
            assert result == "0", f"Kotlin (academic-only) returned {result}, expected 0"

    def test_real_skill_python_returns_one(self):
        """Python is a real skill. Should return 1 year (paid professional)."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of python experience")
            assert result == "1", f"Python returned {result}, expected 1"

    def test_nodejs_skill_returns_one(self):
        """Node.js is a real skill. Should return 1 year."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of node.js experience")
            # Should match "Node.js" in facts and return "1"
            assert result == "1", f"Node.js returned {result}, expected 1"

    def test_nonexistent_skill_returns_zero(self):
        """AWS is in "does NOT have" section. Should return 0."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of aws experience")
            assert result == "0", f"AWS returned {result}, expected 0"

    def test_sponsor_question_when_india(self):
        """For India jobs, sponsor question should return 'No'."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("do you need sponsorship")
            assert result == "No", f"India sponsor returned {result}, expected 'No'"

    def test_sponsor_question_when_usa(self):
        """For USA jobs, sponsor question should return 'Yes'."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "Remote, USA")
            result = answers.rule_answer("do you need visa sponsorship")
            assert result == "Yes", f"USA sponsor returned {result}, expected 'Yes'"

    def test_work_auth_india_yes(self):
        """For India location, work authorization should be 'Yes'."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "Ahmedabad, India")
            result = answers.rule_answer("are you authorized to work in this country")
            assert result == "Yes", f"India auth returned {result}, expected 'Yes'"

    def test_work_auth_usa_no(self):
        """For USA location, work authorization should be 'No'."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "San Francisco, USA")
            result = answers.rule_answer("are you legally authorized to work")
            assert result == "No", f"USA auth returned {result}, expected 'No'"

    def test_bachelor_degree_false(self):
        """Candidate has diploma, not bachelor's. Should return 'No'."""
        with mock_no_llm():
            result = answers.rule_answer("do you have a bachelor's degree")
            assert result == "No", f"Bachelor's returned {result}, expected 'No'"

    def test_relocate_false(self):
        """Candidate won't relocate. Should return 'No'."""
        with mock_no_llm():
            result = answers.rule_answer("are you willing to relocate")
            assert result == "No", f"Relocate returned {result}, expected 'No'"

    def test_remote_yes(self):
        """Candidate is open to remote. Should return 'Yes'."""
        with mock_no_llm():
            result = answers.rule_answer("are you open to remote work")
            assert result == "Yes", f"Remote returned {result}, expected 'Yes'"

    def test_notice_period_immediately(self):
        """Candidate available immediately. Should return matching text."""
        with mock_no_llm():
            result = answers.rule_answer("when can you start")
            # Should match "notice period|when can you start..." rule
            assert result is not None and "immediate" in result.lower(), f"Notice returned {result}"

    def test_professional_years_returns_one(self):
        """Generic 'professional experience' question should return 1 (paid years)."""
        with mock_no_llm():
            result = answers.rule_answer("years of professional experience")
            assert result == "1", f"Professional years returned {result}, expected 1"

    def test_total_experience_handled_properly(self):
        """'Total experience' is ambiguous: should return 1 (paid professional)."""
        with mock_no_llm():
            result = answers.rule_answer("total years of experience")
            # Rule returns "1" (paid professional years)
            assert result == "1", f"Total experience returned {result}, expected 1"

    def test_eeo_questions_decline(self):
        """EEO questions (gender, race, disability) should return decline."""
        with mock_no_llm():
            result = answers.rule_answer("what is your gender")
            assert result == "Decline to self-identify", f"Gender returned {result}"

    def test_background_check_yes(self):
        """Background check question should return 'Yes'."""
        with mock_no_llm():
            result = answers.rule_answer("are you willing to undergo background check")
            assert result == "Yes", f"Background check returned {result}"

    def test_age_18_yes(self):
        """Should confirm 18+ age."""
        with mock_no_llm():
            result = answers.rule_answer("are you 18 years old or older")
            assert result == "Yes", f"Age returned {result}"


# =============================================================================
# filters.py tests: passes_filters(), classify_tier()
# =============================================================================

class TestFiltersLocationAndRole:
    """Test job filtering for location, role exclusions, and tier classification"""

    def test_remote_india_eligible(self, cfg):
        """Remote job open to India should be eligible."""
        job = {
            "title": "Backend Engineer",
            "location": "Remote, India",
            "description": "Remote backend role, open to India.",
            "salary_max": 50000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"Remote India job rejected: {reason}"

    def test_remote_usa_only_ineligible(self, cfg):
        """Remote job restricted to USA should be ineligible."""
        job = {
            "title": "Backend Engineer",
            "location": "Remote, USA only",
            "description": "US-based remote role",
            "salary_max": 50000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"Remote USA-only job accepted: {reason}"

    def test_qa_engineer_filtered(self, cfg):
        """QA Engineer role should be filtered out."""
        job = {
            "title": "QA Engineer",
            "location": "Remote, India",
            "description": "Quality assurance engineering role",
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"QA Engineer accepted: {reason}"

    def test_support_engineer_filtered(self, cfg):
        """Technical Support Engineer should be filtered."""
        job = {
            "title": "Technical Support Engineer",
            "location": "Remote, India",
            "description": "Provide level-1 support to customers",
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"Support Engineer accepted: {reason}"

    def test_backend_engineer_accepted(self, cfg):
        """Backend Engineer in India should be accepted."""
        job = {
            "title": "Backend Software Engineer",
            "location": "Remote, India",
            "description": "Build scalable backend systems",
            "salary_max": 50000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"Backend Engineer rejected: {reason}"

    def test_senior_engineer_not_filtered_classify_as_stretch(self, cfg):
        """Senior Engineer should not be filtered, but classified as STRETCH."""
        job = {
            "title": "Senior Backend Engineer",
            "location": "Remote, India",
            "description": "5+ years required. Build backend systems.",
            "salary_max": 100000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"Senior Engineer rejected: {reason}"
        # Verify it's classified as STRETCH tier
        tier, years, tier_reason = filters.classify_tier(job["title"], job["description"], cfg)
        assert tier == "stretch", f"Senior Engineer tier is {tier}, expected 'stretch'"

    def test_onsite_within_radius_eligible(self, cfg):
        """On-site job within 20km of home should be eligible."""
        job = {
            "title": "Full Stack Engineer",
            "location": "Navrangpura, Ahmedabad",  # ~5km from Shahibaug
            "description": "On-site role in central Ahmedabad",
            "salary_max": 50000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"On-site Navrangpura rejected: {reason}"

    def test_onsite_outside_radius_ineligible(self, cfg):
        """On-site job >20km away should be ineligible."""
        job = {
            "title": "Full Stack Engineer",
            "location": "Sanand",  # ~23km from Shahibaug
            "description": "On-site role in Sanand",
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"On-site Sanand accepted: {reason}"

    def test_night_shift_stricter_radius(self, cfg):
        """Night shift job must be within 10km, not 20km."""
        job = {
            "title": "Night Shift Engineer",
            "location": "Gandhinagar",  # ~15km from Shahibaug
            "description": "Night shift EST hours, 9pm-6am work",
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"Night shift Gandhinagar (15km) accepted: {reason}"

    def test_salary_below_floor_ineligible(self, cfg):
        """Job below ₹25k/month floor should be ineligible."""
        job = {
            "title": "Backend Engineer",
            "location": "Remote, India",
            "description": "Backend role",
            "salary_max": 20000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"Below-floor salary accepted: {reason}"

    def test_salary_above_floor_eligible(self, cfg):
        """Job at or above ₹25k/month should be eligible."""
        job = {
            "title": "Backend Engineer",
            "location": "Remote, India",
            "description": "Backend role",
            "salary_max": 40000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"Above-floor salary rejected: {reason}"

    def test_usd_remote_converts_correctly(self, cfg):
        """USD remote salary should convert at 88 INR/USD and use global floor."""
        # $400/month = 35,200 INR/month > 30,000 INR floor
        job = {
            "title": "Backend Engineer",
            "location": "Remote, worldwide",
            "description": "Remote backend role",
            "salary_max": 400,
            "salary_period": "month",
            "currency": "USD",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"USD remote salary rejected: {reason}"

    def test_no_salary_published_is_ok(self, cfg):
        """Jobs without published salary should be kept (most don't publish)."""
        job = {
            "title": "Backend Engineer",
            "location": "Remote, India",
            "description": "Backend role",
            # No salary_max, salary_min, currency
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"No-salary job rejected: {reason}"


class TestAnswerQuestionChoices:
    """Test answer_question with choice options"""

    def test_work_auth_choice_maps_correctly(self):
        """For work authorization choice question, should pick matching option."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            options = ["Yes, authorized", "No, need sponsorship", "Maybe later"]
            result = answers.answer_question(
                "Are you authorized to work in India?",
                options=options,
                kind="choice"
            )
            assert result == "Yes, authorized", f"Work auth choice returned {result}"

    def test_relocation_choice(self):
        """For relocation choice question, should pick 'No'."""
        with mock_no_llm():
            options = ["Yes, willing to relocate", "No, prefer current location", "Open to offers"]
            result = answers.answer_question(
                "are you willing to relocate",
                options=options,
                kind="choice"
            )
            # Rule answer is "No", should match first option starting with "No"
            assert "no" in result.lower(), f"Relocation choice returned {result}"

    def test_experience_years_bucket_mapping(self):
        """For 'years of experience' choice with buckets, should map to '0-2 years'."""
        with mock_no_llm():
            options = ["0-1 years", "1-2 years", "2-5 years", "5+ years"]
            result = answers.answer_question(
                "years of professional experience",
                options=options,
                kind="choice"
            )
            # Rule answer is "1", should map to "1-2 years" bucket
            assert result == "1-2 years", f"Experience bucket returned {result}"


# =============================================================================
# geo.py tests: is_location_eligible()
# =============================================================================

class TestGeoLocationEligibility:
    """Test location eligibility checking"""

    def test_remote_with_india_mention_eligible(self, cfg):
        """Remote + 'India' mention should be eligible."""
        ok, reason = geo.is_location_eligible(
            "Remote, India",
            None, None,
            cfg
        )
        assert ok, f"Remote India rejected: {reason}"

    def test_remote_with_worldwide_eligible(self, cfg):
        """Remote + 'worldwide' should be eligible."""
        ok, reason = geo.is_location_eligible(
            "Remote, worldwide",
            None, None,
            cfg
        )
        assert ok, f"Remote worldwide rejected: {reason}"

    def test_remote_with_usa_only_ineligible(self, cfg):
        """Remote + 'USA only' should be ineligible."""
        ok, reason = geo.is_location_eligible(
            "Remote, USA only",
            None, None,
            cfg
        )
        assert not ok, f"Remote USA-only accepted: {reason}"

    def test_remote_with_eu_restriction_ineligible(self, cfg):
        """Remote + 'EU only' should be ineligible."""
        ok, reason = geo.is_location_eligible(
            "Remote, Europe only",
            None, None,
            cfg
        )
        assert not ok, f"Remote Europe-only accepted: {reason}"

    def test_onsite_local_eligible(self, cfg):
        """On-site job at Shahibaug (home) should be eligible."""
        ok, reason = geo.is_location_eligible(
            "Shahibaug, Ahmedabad",
            None, None,
            cfg
        )
        assert ok, f"On-site Shahibaug rejected: {reason}"

    def test_onsite_nearby_eligible(self, cfg):
        """On-site job at nearby location (<20km) should be eligible."""
        ok, reason = geo.is_location_eligible(
            "SG Highway, Ahmedabad",  # ~5km from Shahibaug
            None, None,
            cfg
        )
        assert ok, f"On-site SG Highway rejected: {reason}"

    def test_onsite_far_ineligible(self, cfg):
        """On-site job far away (>20km) should be ineligible."""
        ok, reason = geo.is_location_eligible(
            "Vadodara",  # ~100km away
            None, None,
            cfg
        )
        assert not ok, f"On-site Vadodara accepted: {reason}"

    def test_night_shift_10km_radius(self, cfg):
        """Night shift should use 10km radius, not 20km."""
        # Gandhinagar is ~15-18km from Shahibaug - within 20km but outside 10km
        ok, reason = geo.is_location_eligible(
            "Gandhinagar",
            "Night Shift Engineer",  # Triggers night shift detection
            "9pm to 6am EST shift",
            cfg
        )
        assert not ok, f"Night shift Gandhinagar accepted: {reason}"


class TestIntegrationRealWorldScenarios:
    """Integration tests with realistic job postings"""

    def test_senior_engineer_india_remote_high_pay(self, cfg):
        """Senior Engineer, remote India, high salary -> should pass filters."""
        job = {
            "title": "Senior Full Stack Engineer",
            "location": "Remote, India",
            "description": "5-8 years required. Build distributed systems. Remote-first, India-based teams.",
            "salary_max": 120000,
            "currency": "INR",
            "date_posted": "2026-09-20",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"Senior FTE India remote rejected: {reason}"

    def test_us_only_remote_qa(self, cfg):
        """QA Engineer, USA-only remote -> should fail both role and location filters."""
        job = {
            "title": "QA Automation Engineer",
            "location": "Remote, USA only",
            "description": "Quality assurance, test automation. US-based company.",
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert not ok, f"QA USA-only accepted: {reason}"
        # Could be either location or role reason
        assert "qa" in reason.lower() or "remote_restricted" in reason, f"Wrong reason: {reason}"

    def test_onsite_ahmedabad_within_range(self, cfg):
        """On-site job in central Ahmedabad -> should be eligible."""
        job = {
            "title": "Backend Engineer",
            "location": "Bodakdev, Ahmedabad",  # ~5km from Shahibaug
            "description": "On-site backend development in Ahmedabad.",
            "salary_max": 50000,
            "currency": "INR",
        }
        ok, reason = filters.passes_filters(job, cfg)
        assert ok, f"On-site Bodakdev rejected: {reason}"


class TestEdgeCases:
    """Edge case tests for correctness"""
    
    def test_sql_skill_years(self):
        """SQL is a real skill. Should return 1 year."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of sql experience")
            assert result == "1", f"SQL returned {result}, expected 1"
    
    def test_golang_skill_years(self):
        """Go is a real skill. Should return 1 year."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of go experience")
            assert result == "1", f"Go returned {result}, expected 1"
    
    def test_spring_not_available_academic_only(self):
        """Spring is mentioned in 'does NOT have' Java/Spring context. Should be 0."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of spring framework experience")
            # Spring is not mentioned in the positive skills, only in "No production experience with Java/Spring"
            assert result == "0", f"Spring framework returned {result}, expected 0"
    
    def test_kubernetes_not_available(self):
        """Kubernetes explicitly in 'does NOT have'. Should return 0."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of kubernetes experience")
            assert result == "0", f"Kubernetes returned {result}, expected 0"
    
    def test_aws_not_available(self):
        """AWS explicitly in 'does NOT have'. Should return 0."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of aws experience")
            assert result == "0", f"AWS returned {result}, expected 0"
    
    def test_typescript_skill_years(self):
        """TypeScript is a real skill. Should return 1 year."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of typescript experience")
            assert result == "1", f"TypeScript returned {result}, expected 1"
    
    def test_react_skill_years(self):
        """React is a real skill. Should return 1 year."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of react experience")
            assert result == "1", f"React returned {result}, expected 1"
    
    def test_fastapi_skill_years(self):
        """FastAPI is a real skill. Should return 1 year."""
        with mock_no_llm():
            answers.set_job_context("Test Co", "Engineer", "", "India")
            result = answers.rule_answer("years of fastapi experience")
            assert result == "1", f"FastAPI returned {result}, expected 1"
    
    def test_email_rule_match(self):
        """Email field should return candidate's email."""
        with mock_no_llm():
            result = answers.rule_answer("email address")
            assert "saralbanker1@gmail.com" in result, f"Email returned {result}"
    
    def test_phone_rule_match(self):
        """Phone field should return candidate's phone."""
        with mock_no_llm():
            result = answers.rule_answer("phone number")
            assert "+91 9106990136" in result, f"Phone returned {result}"
    
    def test_linkedin_rule_match(self):
        """LinkedIn field should return a URL."""
        with mock_no_llm():
            result = answers.rule_answer("linkedin profile")
            assert result and ("https://" in result or "linkedin" in result.lower()), f"LinkedIn returned {result}"
    
    def test_github_rule_match(self):
        """GitHub field should return a URL."""
        with mock_no_llm():
            result = answers.rule_answer("github")
            assert result and "https://" in result, f"GitHub returned {result}"
    
    def test_location_rule_match(self):
        """Location field should return candidate's location."""
        with mock_no_llm():
            result = answers.rule_answer("where are you located")
            assert "ahmedabad" in result.lower() or "india" in result.lower(), f"Location returned {result}"
    
    def test_degree_rule_match(self):
        """Degree question should return diploma info."""
        with mock_no_llm():
            result = answers.rule_answer("highest level of education")
            assert result and "diploma" in result.lower(), f"Degree returned {result}"
