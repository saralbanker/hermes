"""Offline tests for src/filters.py — no network, no Ollama."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from filters import classify_tier, passes_filters, role_priority, salary_ok
from states import CORE, STRETCH


def load_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    return yaml.safe_load(open(cfg_path))


CFG = load_config()


def make_job(**overrides) -> dict:
    job = {
        "title": "Software Engineer",
        "description": "We build web applications.",
        "location": "Remote, India",
        "date_posted": None,
        "salary_min": None,
        "salary_max": None,
        "currency": None,
    }
    job.update(overrides)
    return job


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------

def test_salary_india_below_floor_rejected():
    job = make_job(salary_min=20000, salary_max=20000, currency="INR")
    ok, reason = salary_ok(job, CFG)
    assert not ok
    assert reason.startswith("salary_below_floor")


def test_salary_india_at_floor_accepted():
    job = make_job(salary_min=25000, salary_max=25000, currency="INR")
    ok, reason = salary_ok(job, CFG)
    assert ok


def test_salary_global_below_floor_rejected():
    job = make_job(salary_min=300, salary_max=300, currency="USD")
    ok, reason = salary_ok(job, CFG)
    assert not ok
    assert reason.startswith("salary_below_floor")


def test_salary_global_yearly_accepted():
    job = make_job(salary_min=60000, salary_max=60000, currency="USD")
    ok, reason = salary_ok(job, CFG)
    assert ok


def test_salary_unpublished_accepted():
    job = make_job(salary_min=None, salary_max=None)
    ok, reason = salary_ok(job, CFG)
    assert ok
    assert reason == "salary_unpublished"


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------

# A realistic >=400-char posting in the candidate's stack (positive evidence is required).
LONG_DESC = (
    "About the role\nWe build AI-powered web products. You will build and maintain REST APIs and "
    "services in Python (FastAPI) and TypeScript, ship React features, and work with PostgreSQL, "
    "Redis and Docker. You will also integrate LLM and RAG pipelines into our application and "
    "write tests for everything you ship. We work remotely across time zones and review code "
    "together every day. Our engineers own features end to end, from design review through "
    "deployment and monitoring, and we value clear writing and small, frequent releases.\n"
)


def long_desc(requirements: str = "") -> str:
    return LONG_DESC + (f"\nRequirements:\n{requirements}\n" if requirements else "")


def test_junior_is_core():
    tier, years, reason = classify_tier("Junior Software Engineer", long_desc("- 0-2 years experience"), CFG)
    assert tier == CORE


def test_unstated_experience_is_core():
    tier, years, reason = classify_tier("Software Engineer", LONG_DESC, CFG)
    assert tier == CORE
    assert years is None


def test_long_desc_fixture_is_long_enough():
    assert len(LONG_DESC) >= 400


def test_stub_description_with_neutral_title_is_low_confidence_stretch():
    from filters import assess
    qual = assess("Software Engineer", "Build great software.", CFG)
    assert qual.decision == "qualified" and qual.tier == STRETCH
    assert qual.confidence <= 0.5 and qual.reasons


def test_senior_backend_is_stretch():
    tier, years, reason = classify_tier("Senior Backend Engineer", "3+ years required", CFG)
    assert tier == STRETCH


def test_founding_engineer_is_stretch():
    tier, years, reason = classify_tier("Founding Engineer", "Join our early team.", CFG)
    assert tier == STRETCH


def test_ten_plus_years_filtered():
    tier, years, reason = classify_tier("Software Engineer", "10+ years of experience required", CFG)
    assert tier is None and years == 10
    assert reason.startswith("qualification:seniority:years:10")


def test_engineering_manager_filtered():
    tier, years, reason = classify_tier("Engineering Manager", "Manage a team of engineers.", CFG)
    assert tier is None
    assert "people_management" in reason


def test_years_range_parses_low_end():
    tier, years, reason = classify_tier("Software Engineer", "3-5 years of experience", CFG)
    assert years == 3


def test_years_plus_parses():
    tier, years, reason = classify_tier("Software Engineer", "5+ years of experience", CFG)
    assert years == 5


def test_non_requirement_years_context_ignored():
    tier, years, reason = classify_tier(
        "Software Engineer", LONG_DESC + "Our company was founded 10 years ago and is growing fast.", CFG)
    assert years is None
    assert tier == CORE


# ---------------------------------------------------------------------------
# Role exclusions
# ---------------------------------------------------------------------------

def test_qa_engineer_excluded():
    tier, years, reason = classify_tier("QA Engineer", "Manual and automated testing.", CFG)
    assert tier is None
    assert "qa_only" in reason


def test_technical_support_excluded():
    tier, years, reason = classify_tier("Technical Support Engineer", "Help customers with issues.", CFG)
    assert tier is None
    assert "support" in reason


def test_sdr_excluded():
    tier, years, reason = classify_tier("SDR", "Generate sales pipeline.", CFG)
    assert tier is None
    assert "sales" in reason


def test_manual_tester_excluded():
    tier, years, reason = classify_tier("Manual Tester", "Execute manual test cases.", CFG)
    assert tier is None
    assert "qa_only" in reason


# Real leaks the owner reported: both slipped through before the "teaching" exclusion.
def test_teachers_tutors_mentors_for_academy_excluded():
    tier, years, reason = classify_tier(
        "Online Teachers/Tutors/Mentors for Software Academy",
        "Teach students how to code.", CFG)
    assert tier is None
    assert "teaching" in reason


def test_ai_coding_trainer_excluded():
    tier, years, reason = classify_tier("AI Coding Trainer", "Train students in AI concepts.", CFG)
    assert tier is None
    assert "teaching" in reason


def test_instructor_and_teaching_assistant_excluded():
    for title in ("Software Instructor", "Teaching Assistant - Web Development",
                  "Python Tutor", "Bootcamp Mentor for Coding Academy",
                  "Front End Developer with Generative AI Trainer",
                  "Trainer – Physical AI & Robotics", "AI Trainer"):
        tier, years, reason = classify_tier(title, "", CFG)
        assert tier is None, title
        assert "teaching" in reason, title


def test_ml_model_trainer_not_excluded_as_teaching():
    """'Trainer'/'mentor' alone must not catch ML roles that train MODELS, not people."""
    tier, years, reason = classify_tier("ML Model Trainer", "Train and fine-tune ML models.", CFG)
    assert "teaching" not in reason


def test_mentoring_junior_engineers_duty_does_not_exclude_a_real_engineering_role():
    """Title-only match: a normal engineering job that mentions mentoring as a duty in the
    description must not be rejected — only the TITLE decides the teaching exclusion."""
    tier, years, reason = classify_tier(
        "Senior Backend Engineer", "You will mentor junior engineers and review code.", CFG)
    assert tier is not None


def test_forward_deployed_engineer_accepted():
    tier, years, reason = classify_tier(
        "Forward Deployed Engineer",
        "You will build and ship software directly at customer sites.", CFG)
    assert tier is not None


# ---------------------------------------------------------------------------
# role_priority ordering
# ---------------------------------------------------------------------------

def test_role_priority_ordering():
    ai = role_priority("AI Engineer", "Work on LLM applications.")
    backend = role_priority("Backend Engineer", "Build APIs.")
    fullstack = role_priority("Full Stack Engineer", "Build web apps.")
    general = role_priority("Software Engineer", "General engineering work.")
    automation = role_priority("Automation Engineer", "Build internal tools.")
    frontend = role_priority("Frontend Engineer", "Build UI components.")
    assert ai > backend > fullstack > general > automation > frontend


# ---------------------------------------------------------------------------
# Staleness / passes_filters integration
# ---------------------------------------------------------------------------

def test_stale_posting_expired():
    job = make_job(date_posted="2020-01-01T00:00:00Z")
    ok, reason = passes_filters(job, CFG)
    assert not ok
    assert reason == "expired"


def test_fresh_posting_passes():
    job = make_job(location="Remote, India")
    ok, reason = passes_filters(job, CFG)
    assert ok


def test_company_blurb_words_do_not_exclude_engineering_roles():
    from filters import _exclusion_reason
    desc = ("We build AI tools for sales and marketing teams. Our customer support platform "
            "serves 2k companies. You will design Python APIs and React UIs.")
    assert _exclusion_reason("Full Stack Engineer", desc) is None


def test_support_duties_in_description_exclude():
    from filters import _exclusion_reason
    desc = "This role will provide advanced support, administration and optimization for Amazon Connect."
    assert _exclusion_reason("Amazon Connect L3 SME", desc) == "support"


# ---------------------------------------------------------------------------
# Stack mismatch (title-only), seniority mismatch, tightened years
# ---------------------------------------------------------------------------

import pytest


@pytest.mark.parametrize("title,token", [
    ("Senior .NET Software Engineer", ".net"), ("C# Developer", "c#"), ("PHP Laravel Developer", "php"),
    ("Sr. Java React Full Stack Developer", "java"), ("Spring Boot Engineer", "spring boot"),
    ("SAP ABAP Engineer", "sap"), ("Ruby on Rails Engineer", "ruby on rails"),
    ("iOS Engineer", "ios"), ("Android Developer", "android"), ("AWS Cloud Engineer", "cloud engineer"), ("Forward Deployed Engineer (Java)", "java"),
    ("Senior DevOps Engineer", "devops"), ("Machine Learning Engineer", "machine learning engineer"),
    ("Data Scientist", "data scientist"),
])
def test_title_role_identity_alone_goes_to_review_never_rejects(title, token):
    """A single title signal is non-decisive: review (human release), not a rejection."""
    tier, _years, reason = classify_tier(title, "Build things.", CFG)
    assert tier is not None
    assert reason == f"qualification_review:stack:title_role:{token}"


@pytest.mark.parametrize("title,reqs", [
    ("C# Developer", "- 3+ years of C# and .NET Core\n- Azure"),
    ("PHP Laravel Developer", "- Strong PHP and Laravel\n- MySQL"),
    ("Salesforce Developer", "- Salesforce Apex, 3 years of Salesforce\n- SOQL"),
    ("Embedded Software Engineer", "- Proficient in C++ and firmware development"),
])
def test_title_plus_required_section_corroborate_to_reject(title, reqs):
    tier, _years, reason = classify_tier(title, long_desc(reqs), CFG)
    assert tier is None
    assert reason.startswith("qualification:stack:")


@pytest.mark.parametrize("title", [
    "Senior Software Engineer (Java and JavaScript ecosystem)",
    "Full Stack Engineer (AWS)", "AI Engineer with GCP", "Azure AI Engineer", "Full Stack JavaScript Developer",
    "AI/ML Engineer (LLM & RAG)", "Machine Learning Engineer, GenAI Applications",
    "Backend Engineer (Python, AI Agents)", "Software Engineer, Spring 2027 Intern Program", "Node.js Backend Engineer",
])
def test_secondary_or_neutralised_stack_mentions_do_not_reject(title):
    tier, _years, reason = classify_tier(title, long_desc("- Python, React, PostgreSQL"), CFG)
    assert tier in (CORE, STRETCH) and not reason.startswith("qualification_review")


@pytest.mark.parametrize("title", [
    "Staff Software Engineer", "Principal Engineer", "Distinguished Engineer", "Software Architect",
])
def test_staff_plus_title_alone_is_review(title):
    tier, _years, reason = classify_tier(title, long_desc(), CFG)
    assert tier is not None and reason.startswith("qualification_review:seniority:title_staff_plus")


def test_staff_plus_title_with_years_or_leadership_duties_is_rejected():
    assert classify_tier("Principal Engineer", long_desc("- 10+ years of experience"), CFG)[0] is None
    desc = long_desc("- You will lead a team of engineers and own hiring")
    assert classify_tier("Staff Software Engineer", desc, CFG)[0] is None


def test_senior_and_founding_remain_stretch():
    assert classify_tier("Senior Backend Developer", long_desc(), CFG)[0] == STRETCH
    assert classify_tier("Sr. Software Engineer", long_desc(), CFG)[0] == STRETCH
    assert classify_tier("Founding Engineer", long_desc(), CFG)[0] == STRETCH


def test_full_stack_developer_is_core():
    assert classify_tier("Full Stack Developer", long_desc(), CFG)[0] == CORE


def test_three_plus_years_is_stretch():
    tier, years, _ = classify_tier("Software Engineer", long_desc("- 3+ years of experience."), CFG)
    assert (tier, years) == (STRETCH, 3)


def test_five_plus_years_is_filtered():
    tier, years, reason = classify_tier("Software Engineer", long_desc("- 5+ years of experience."), CFG)
    assert tier is None and years == 5 and reason.startswith("qualification:seniority:years:5")


def test_two_years_is_core():
    assert classify_tier("Software Engineer", long_desc("- 2+ years of experience."), CFG)[0] == CORE


def test_passes_filters_review_fails_closed_with_review_reason():
    ok, reason = passes_filters(make_job(title="PHP Laravel Developer"), CFG)
    assert not ok and reason.startswith("qualification_review:")


def test_passes_filters_rejects_corroborated_stack_mismatch():
    job = make_job(title="PHP Laravel Developer", description=long_desc("- Strong PHP and Laravel"))
    ok, reason = passes_filters(job, CFG)
    assert not ok and reason.startswith("qualification:stack:")
