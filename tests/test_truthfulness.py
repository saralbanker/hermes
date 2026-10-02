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


def test_project_number_misattribution_is_rejected():
    # A real letter the LLM produced for Snowflake: true numbers, wrong owner — Neuro-Zenith's
    # "70,000 lines" pasted into a paragraph about Hermes, which has no stated line count.
    letter = (
        "This role aligns with my work on LLM-based automation, such as Hermes, which uses "
        "local LLMs and Playwright to automate job searches.\n\n"
        "I built Hermes — a Python-based pipeline that scrapes job listings and scores them "
        "with a local LLM (Ollama). The system runs via systemd and includes CI checks, with "
        "70,000 lines of code across multiple services, showing a foundation in scalable, "
        "production-ready tooling."
    )
    problems = validate_letter(letter)
    assert any("different project" in p for p in problems)


def test_project_number_correctly_attributed_is_accepted():
    letter = ("I've built local-first AI platforms with multi-provider LLM routing.\n\n"
              "Neuro-Zenith features a React frontend, a FastAPI inference service, and RAG "
              "with pgvector. The system has 70,000 lines of code across 400+ files.")
    assert not validate_letter(letter)


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
        assert "9106990136" in text and text.index("Neuro-Zenith —") < text.index("AWIS —")


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


def test_llm_screening_answer_hallucinated_percentage_is_rejected(monkeypatch):
    # Reproduces a real local-model failure: asked an open screening question, qwen3 answered
    # with a fabricated "60% faster" claim instead of grounded facts. llm_answer must run the
    # same validator tailor.py uses for cover letters, retry once, and give up rather than
    # ever returning a hyped/fabricated number.
    import answers
    calls = {"n": 0}

    def fake_chat(prompt, system="", temperature=0.0, max_tokens=0):
        calls["n"] += 1
        return "I reduced latency by 60% using a caching layer." if calls["n"] == 1 else "UNKNOWN"

    monkeypatch.setattr(answers, "chat", fake_chat)
    assert answers.llm_answer("What impact have you made?") is None
    assert calls["n"] == 2


def test_llm_screening_answer_grounded_in_facts_is_accepted(monkeypatch):
    import answers
    monkeypatch.setattr(answers, "chat", lambda *a, **k: "I built AWIS, an event-sourced "
                        "workflow engine in Go with 773 test functions.")
    out = answers.llm_answer("Tell me about a project you're proud of")
    assert out and "773" in out


def test_take_home_assignment_link_is_not_answered_with_the_profile_github():
    # Real Cloudflare field: matches the generic "github" rule by substring, but asking
    # for a repo isn't the same as asking for the candidate's profile — answering it with
    # github.com/saralbanker would read as a claim the assignment was done.
    from answers import rule_answer
    assert rule_answer("Optional Assignment: Please share GitHub repo URL for the project here") is None
    assert rule_answer("Take-home exercise submission link") is None
    assert rule_answer("GitHub URL") == "https://github.com/saralbanker"  # unaffected: a real profile ask


@pytest.mark.parametrize("orphaned_option_label", ["LinkedIn", "Glassdoor", "Notion Blog", "Notion Website"])
def test_orphaned_checkbox_option_label_is_never_llm_guessed(orphaned_option_label, monkeypatch):
    # Real bug, live on Ashby/Notion: a "how did you hear about us?" multi-select renders as
    # independent checkboxes each named after ITS OWN option text (grouping-by-shared-`name`
    # never fires), so each option reaches answer_question alone as e.g. label="LinkedIn",
    # kind="boolean", with zero surrounding context. Before this fix, that went to the LLM,
    # which checked "LinkedIn" as the discovery channel by word association alone — a
    # fabricated claim nothing in facts.md supports. It must now be refused before the LLM
    # is even called (monkeypatching chat to explode proves the LLM path is never entered).
    import answers
    monkeypatch.setattr(answers, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError(
        "LLM must not be asked to guess a bare option label")))
    assert answers.answer_question(orphaned_option_label, kind="boolean") is None


def test_real_boolean_question_still_reaches_the_llm_when_no_rule_answers_it(monkeypatch):
    import answers
    monkeypatch.setattr(answers, "chat", lambda *a, **k: "Yes")
    assert answers.answer_question("Are you comfortable pairing with teammates daily?", kind="boolean") == "Yes"


def test_us_person_export_control_question_answered_no():
    # Absolute citizenship fact, independent of the job's own country (unlike sponsorship).
    from answers import set_job_context
    set_job_context("Snowflake", "Software Engineer", "", "Remote")
    assert answer_question(
        'A "U.S. person" is a citizen, legal permanent resident, or legal temporary resident '
        "of the United States. Are you a U.S. person?", ["Yes", "No"]) == "No"
    assert answer_question("Please confirm your export control / ITAR status", ["Yes", "No"]) == "No"
    set_job_context("", "", "", "")


@pytest.mark.parametrize("options", [
    ["I Agree", "I Do Not Agree"],
    ["I agree to the Candidate Privacy Policy", "I do not agree"],
    ["Accept", "Decline"],
])
def test_consent_checkbox_picks_the_affirmative_option(options):
    # Greenhouse/Ashby render "Acknowledge/Confirm the privacy policy" as a radio pair
    # instead of a single checkbox; the rule answer ("Yes") must still map onto it —
    # this was the reason real Cloudflare/OpenTable applications stalled at form-fill.
    answer = answer_question("Acknowledge/Confirm — Candidate Privacy Policy", options)
    assert answer == options[0]


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
