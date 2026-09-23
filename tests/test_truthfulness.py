"""Cover letters, screening answers and resumes must never overstate the candidate."""
import subprocess
from pathlib import Path

import pytest
import yaml

from answers import answer_question
from tailor import select_resume_variant, template_letter, validate_letter

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("text", [
    "I have 4 years of professional experience with Node.js.",
    "With five years of industry experience I can lead the team.",
    "I bring experience with AWS and Kubernetes in production.",
    "My healthcare background matches precisely.",
    "I reduced costs by 30%.",
])
def test_fabricated_letters_rejected(text):
    assert validate_letter(text)


def test_truthful_letter_passes():
    assert not validate_letter("I have about 4 years of hands-on software development and "
                               "about 1 year of paid freelance work. I built AWIS in Go.")


@pytest.mark.parametrize("variant", ["ai", "backend", "fullstack"])
def test_template_letters_pass_validator(variant):
    job = {"company": "Acme", "title": "Engineer", "description": ""}
    assert not validate_letter(template_letter(job, variant))


def test_experience_answers_are_honest():
    assert answer_question("Years of experience", kind="text") == "1"
    prose = answer_question("How many years of experience do you have?", kind="textarea")
    assert "1 year of paid" in prose and "4 years of hands-on" in prose
    assert answer_question("Do you have a bachelor's degree?", ["Yes", "No"]) == "No"
    assert answer_question("Will you require visa sponsorship?", ["Yes", "No"]) == "No"


def test_resume_variant_routing():
    assert select_resume_variant("AI Engineer (LLM)", "") == "ai"
    assert select_resume_variant("Backend Engineer", "") == "backend"
    assert select_resume_variant("Full Stack Developer", "") == "fullstack"


def test_resume_variants_distinct_and_awis_below_neuro_zenith():
    cfg = yaml.safe_load(open(ROOT / "profile" / "resume.yaml"))
    for name, v in cfg["variants"].items():
        order = v["project_order"]
        assert "awis" in order and order.index("neuro-zenith") < order.index("awis"), name
    pdfs = sorted((ROOT / "resumes").glob("resume-*.pdf"))
    assert len({p.read_bytes() for p in pdfs}) == len(pdfs) == 3
    for p in pdfs:
        info = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True).stdout
        pages = int(next(l.split()[-1] for l in info.splitlines() if l.startswith("Pages")))
        assert 1 <= pages <= 2, p
        text = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True).stdout
        assert "9016990136" in text and text.index("Neuro-Zenith —") < text.index("AWIS —")


@pytest.mark.parametrize("question,expected", [
    ("How many years of amazon connect experience do you have?", "0"),
    ("How many years of experience do you have with Kubernetes?", "0"),
    ("Years of AWS experience", "0"),
    ("Years of Java/Spring experience", "0"),
    ("Years of Python experience", "1"),
    ("How many years of React experience do you have?", "1"),
    ("Total years of experience", "1"),
])
def test_skill_specific_years_are_grounded(question, expected):
    assert answer_question(question, kind="text") == expected


def test_sponsorship_and_authorization_depend_on_country():
    from answers import set_job_context
    set_job_context("Acme", "Engineer", "", "Remote (India)")
    assert answer_question("Will you require visa sponsorship?", ["Yes", "No"]) == "No"
    assert answer_question("Are you authorized to work in the United States?", ["Yes", "No"]) == "No"
    set_job_context("Webflow", "Engineer", "", "CA Remote (BC & ON only); U.S. Remote")
    assert answer_question("Will you now or in the future require sponsorship?", ["Yes", "No"]) == "Yes"
    assert answer_question("Do you have legal authorization to work in the country of the job?",
                           ["Yes", "No"]) == "No"
    set_job_context("", "", "", "")
