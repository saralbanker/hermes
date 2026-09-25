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

def test_junior_is_core():
    tier, years, reason = classify_tier("Junior Software Engineer", "0-2 years experience", CFG)
    assert tier == CORE


def test_unstated_experience_is_core():
    tier, years, reason = classify_tier("Software Engineer", "Build great software.", CFG)
    assert tier == CORE
    assert years is None


def test_senior_backend_is_stretch():
    tier, years, reason = classify_tier("Senior Backend Engineer", "5+ years required", CFG)
    assert tier == STRETCH


def test_founding_engineer_is_stretch():
    tier, years, reason = classify_tier("Founding Engineer", "Join our early team.", CFG)
    assert tier == STRETCH


def test_ten_plus_years_filtered():
    tier, years, reason = classify_tier("Staff Engineer", "10+ years of experience required", CFG)
    assert tier is None
    assert "too_senior" in reason


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
        "Software Engineer", "Our company was founded 10 years ago and is growing fast.", CFG)
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
    assert tier is not None


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
