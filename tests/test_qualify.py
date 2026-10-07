"""Offline tests for src/qualify.py (multi-evidence qualification engine) and its persistence."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from filters import assess, classify_tier, passes_filters, qualification_fields  # noqa: E402
from qualify import QUALIFY_VERSION, qualify  # noqa: E402
from states import CORE, STRETCH  # noqa: E402

CFG = yaml.safe_load((Path(__file__).parent.parent / "config.yaml").read_text())

PAD = ("We are a small remote-first team that values clear writing, code review and steady, "
       "well-tested releases. You will own features end to end, from design through monitoring. "
       "We hire people who like small teams, document their decisions and help each other debug "
       "hard problems, and we ship to real customers every single week without drama.\n\n")
STACK = "Requirements:\n- Node.js, React and PostgreSQL\n- Python or TypeScript\n- Docker\n"


def check(title: str, desc: str, decision: str):
    qual = qualify(title, desc, CFG)
    assert qual.decision == decision, (title, qual.decision, qual.reasons)
    assert qual.reasons and all(qual.reasons)
    assert qual.version == QUALIFY_VERSION
    return qual


# --- Required cases -----------------------------------------------------------------------

def test_android_intern_is_not_rejected():
    q = qualify("Android App Developer Intern", PAD + "Build Android apps in Kotlin.\nRequirements:\n- Kotlin, Android\n", CFG)
    assert q.decision != "rejected" and q.reasons


def test_java_developer_with_required_java_years_is_rejected():
    desc = PAD + "Requirements:\n- 3+ years of Java and Spring Boot\n- SQL\n"
    q = check("Java Developer", desc, "rejected")
    assert q.tier is None and q.reasons[0].startswith("stack:")
    assert "title_role:java" in q.reasons[0] and "desc_required" in q.reasons[0]


def test_weak_platform_token_in_title_never_rejects():
    q = check("Full Stack Engineer (AWS)", PAD + STACK, "qualified")
    assert q.tier in (CORE, STRETCH)


def test_azure_ai_engineer_with_llm_requirements_is_not_rejected():
    desc = PAD + "Requirements:\n- LLM and RAG pipelines\n- Python\n"
    assert qualify("Azure AI Engineer", desc, CFG).decision == "qualified"


def test_seven_years_minimum_is_decisive_for_clean_title():
    q = check("Software Engineer", PAD + STACK + "- Minimum 7 years of experience\n", "rejected")
    assert q.required_years == 7 and q.reasons[0].startswith("seniority:years:7")
    assert any(s.is_decisive for s in q.signals)


def test_years_in_preferred_section_are_ignored():
    desc = PAD + "Requirements:\n- 1-2 years of experience\n- Python\n\nNice to have:\n- 5+ years of experience\n"
    q = check("Software Engineer", desc, "qualified")
    assert q.required_years == 1


def test_preferred_cue_inside_parentheses_does_not_demote_requirement():
    desc = (PAD + "**Required Skills:**\n\n* 5+ yrs of proficiency in Python (especially pipelines) or "
            "TypeScript (experience navigating large codebases like VSCode a plus)\n")
    q = check("Senior SWE - Python / TypeScript", desc, "rejected")
    assert q.required_years == 5


def test_senior_title_without_years_is_qualified_stretch():
    q = check("Senior Backend Engineer", PAD + STACK, "qualified")
    assert q.tier == STRETCH


def test_staff_title_single_source_is_review_and_with_years_is_rejected():
    q = check("Staff Engineer", PAD + STACK, "review")
    assert q.tier in (CORE, STRETCH) and q.confidence == 0.5
    check("Staff Engineer", PAD + STACK + "- 8+ years of experience\n", "rejected")


def test_german_posting_is_rejected_by_constraint():
    desc = "Requirements:\n- Fließend Deutsch in Wort und Schrift\n- React\n"
    q = check("Fullstack Entwickler", PAD + desc, "rejected")
    assert q.reasons[0].startswith("constraint:") and "german" in q.reasons[0]
    german = ("Wir suchen einen Entwickler für unser Team. Sie arbeiten mit React und Node und haben "
              "Erfahrung mit der Entwicklung von Anwendungen. Wir bieten Ihnen ein modernes Umfeld und "
              "die Möglichkeit, von zu Hause zu arbeiten. Sie sind ein Teamplayer und haben Spaß an Technik.")
    assert check("Fullstack Entwickler", german, "rejected").reasons[0].startswith("constraint:")


def test_title_without_engineering_words_is_review_when_duties_exist():
    desc = PAD + "You will build LLM services and Python APIs.\nRequirements:\n- Python, LLM, FastAPI\n"
    check("Member of Technical Staff - AI", desc, "review")


def test_graphic_designer_stays_rejected_by_policy_gate():
    qual = assess("Graphic Designer", PAD + STACK, CFG)
    assert qual.decision == "rejected" and qual.reasons == ("policy:non_engineering_title",)
    assert classify_tier("Graphic Designer", PAD, CFG)[2] == "excluded_role:non_engineering_title"
    assert check("Graphic Designer", PAD, "rejected").reasons[0].startswith("role:")


def test_data_scientist_training_rejected_but_llm_engineer_qualified():
    check("Data Scientist", PAD + "Requirements:\n- Model training with PyTorch\n- Python\n", "rejected")
    desc = PAD + "Requirements:\n- Python, RAG and LLM apps\n- Some machine learning background\n"
    check("AI Engineer (LLM, RAG)", desc, "qualified")


@pytest.mark.parametrize("title,desc", [
    ("Software Engineer", PAD + STACK + "- Familiar with Java\n"),                 # lone mention
    ("Java Developer", "Build things."),                                           # lone title identity
    ("Staff Engineer", PAD + STACK),                                               # lone seniority title
    ("Software Engineer", PAD + STACK + "- 3+ years of experience\n"),             # lone mid years
    ("Software Engineer", PAD + STACK + "- Certification is mandatory\n"),         # lone strong constraint
    ("Fullstack Entwickler", PAD + STACK),                                         # lone title language
    ("Software Engineer", PAD + STACK + "- 4 years of React\n"),                   # lone per-skill years
    ("DevOps Engineer", PAD + STACK),                                              # lone platform identity
])
def test_single_non_decisive_signal_never_rejects(title, desc):
    qual = qualify(title, desc, CFG)
    assert qual.decision != "rejected", (title, qual.reasons)
    assert qual.reasons


# --- Addendum: positive evidence ------------------------------------------------------------

def test_long_description_without_candidate_stack_and_other_primary_stack_is_rejected():
    desc = PAD + "Requirements:\n- 3 years of experience with C# and .NET Core\n- SQL Server\n"
    q = check("Software Engineer", desc, "rejected")
    assert q.reasons[0].startswith("stack:no_core_evidence+primary_other:")


def test_long_description_without_stack_or_dev_duties_is_rejected_no_dev_evidence():
    desc = PAD + "Requirements:\n- Excellent communication\n- Willingness to travel\n"
    q = check("Software Engineer", desc.replace("write", "draft").replace("own features", "own accounts"),
              "rejected")
    assert "no_dev_evidence" in q.reasons[0]


def test_stub_description_with_neutral_title_is_low_confidence_stretch():
    q = check("Software Engineer", "Join our team.", "qualified")
    assert q.tier == STRETCH and q.confidence <= 0.5


@pytest.mark.parametrize("tokens", ["Rust", "Solidity smart contracts", "UiPath RPA", "Snowflake, dbt and Airflow",
                                    "Unity game engine", "Salesforce Commerce SFCC", "CUDA kernel"])
def test_other_primary_domains_without_core_stack_are_rejected(tokens):
    desc = PAD + f"Requirements:\n- Experience with {tokens}\n- Strong problem solving\n"
    check("Software Engineer", desc, "rejected")


# --- Addendum: non-engineering duties -------------------------------------------------------

def test_non_engineering_duties_override_engineering_sounding_title():
    desc = PAD + ("Requirements:\n- Video production and video editing experience\n- Content creation for "
                  "social channels\n- Python\n")
    q = check("Content Engineer", desc, "rejected")
    assert q.reasons[0].startswith("role:non_engineering_duties")


def test_single_non_engineering_duty_is_not_enough_to_reject():
    desc = PAD + STACK + "- Occasionally join pre-sales calls\n"
    assert qualify("Solutions Developer", desc, CFG).decision != "rejected"


def test_bi_analyst_dashboards_and_implementation_support_are_non_engineering():
    desc = PAD + "Requirements:\n- Build dashboards in Power BI\n- Implementation support for customers\n"
    check("Data Engineer", desc, "rejected")


# --- Addendum: non-job postings, languages, certification ----------------------------------

@pytest.mark.parametrize("title,line", [
    ("Software Engineer - Talent Pool", "Join our talent pool for future opportunities."),
    ("Software Engineering Fellowship", "A learning programme for new graduates."),
    ("Software Engineer", "Candidates pay a course fee of Rs 40,000 for the training program."),
    ("Research Engineer", "A PhD is required for this role."),
    ("Postdoctoral Software Engineer", "Research position."),
    ("Software Engineer Intern", "Open to students currently enrolled in a university degree."),
])
def test_non_job_postings_are_decisively_rejected(title, line):
    q = check(title, PAD + STACK + line + "\n", "rejected")
    assert q.reasons[0].startswith("constraint:")


def test_phd_preferred_and_german_plus_do_not_reject():
    desc = PAD + STACK + "\nNice to have:\n- PhD preferred\n- German is a plus\n"
    check("Software Engineer", desc, "qualified")


@pytest.mark.parametrize("line", ["Fluent Portuguese is required.", "Spanish: native level required.",
                                  "Business-level French and English."])
def test_required_non_english_language_is_decisive(line):
    q = check("Software Engineer", PAD + STACK + line + "\n", "rejected")
    assert "language_required" in q.reasons[0]


def test_posting_written_mostly_in_spanish_or_portuguese_is_rejected():
    es = ("Buscamos un desarrollador con experiencia en el desarrollo de aplicaciones para nuestro equipo. "
          "Nuestra empresa ofrece trabajo remoto y una experiencia única con los mejores profesionales "
          "del sector, para que el equipo crezca con una cultura de trabajo en la que se valora el talento.")
    pt = ("Procuramos um desenvolvedor para o nosso time, com experiência em aplicações web. Você vai "
          "trabalhar com uma equipe que valoriza o talento e oferece um ambiente de trabalho remoto para "
          "que nós possamos crescer juntos, com os melhores profissionais do mercado e uma cultura aberta.")
    for desc in (es, pt):
        assert check("Software Engineer", desc, "rejected").reasons[0].startswith("constraint:")


def test_mandatory_certification_is_strong_but_needs_corroboration():
    cert = "- AWS certification is mandatory\n"
    assert qualify("Software Engineer", PAD + STACK + cert, CFG).decision == "review"
    q = qualify("Software Engineer", PAD + STACK + cert + "- Fluent German\n", CFG)
    assert q.decision == "rejected"


# --- Addendum: titles mislead in both directions --------------------------------------------

@pytest.mark.parametrize("title", ["Senior Backend Engineer", "Lead Developer"])
def test_low_years_evidence_beats_lead_or_senior_title(title):
    desc = PAD + "Requirements:\n- 1-2 years of experience\n- Python, React\n"
    q = check(title, desc, "qualified")
    assert q.required_years == 1
    assert all(s.dimension != "seniority" for s in q.signals if s.polarity < 0)


# --- Persistence ----------------------------------------------------------------------------

QUAL_COLUMNS = {"qual_decision", "qual_confidence", "qual_version", "qual_evidence"}


def test_qual_columns_exist_after_init(temp_db):
    conn = temp_db.get_conn()
    assert QUAL_COLUMNS <= {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    temp_db.init_db()  # idempotent
    conn.close()


def test_qualification_fields_roundtrip_json():
    fields = qualification_fields("Java Developer", PAD + "Requirements:\n- 3+ years of Java\n", CFG)
    assert set(fields) == QUAL_COLUMNS and fields["qual_decision"] == "rejected"
    evidence = json.loads(fields["qual_evidence"])
    assert evidence["reasons"] and evidence["signals"]


def test_discovery_writes_qual_columns(temp_db, monkeypatch):
    import pandas as pd
    import discover
    monkeypatch.setattr(discover, "get_all_dedupe_keys", lambda: set())
    df = pd.DataFrame([{
        "job_url": "https://example.com/jobs/1", "company": "Acme", "title": "Backend Engineer",
        "location": "Remote, India", "site": "indeed", "description": PAD + STACK,
    }])
    discover.save_to_db(df, CFG)
    row = temp_db.get_conn().execute("SELECT * FROM jobs").fetchone()
    assert row["qual_decision"] == "qualified" and row["qual_version"] == QUALIFY_VERSION
    assert json.loads(row["qual_evidence"])["reasons"]


def test_review_posting_is_stored_as_manual_review(temp_db, monkeypatch):
    import pandas as pd
    import discover
    monkeypatch.setattr(discover, "get_all_dedupe_keys", lambda: set())
    df = pd.DataFrame([{
        "job_url": "https://example.com/jobs/2", "company": "Acme", "title": "Staff Engineer",
        "location": "Remote, India", "site": "indeed", "description": PAD + STACK,
    }])
    discover.save_to_db(df, CFG)
    row = temp_db.get_conn().execute("SELECT status, status_reason, qual_decision FROM jobs").fetchone()
    assert row["status"] == "manual_review" and row["status_reason"].startswith("qualification_review:")
    assert row["qual_decision"] == "review"


def test_cleanup_rescoring_never_overwrites_submitted_rows(temp_db):
    import cleanup_backlog
    conn = temp_db.get_conn()
    snapshot = ("qualified", 0.9, "qe-0", '{"reasons":["original"]}')
    for url, status in (("u1", "submitted"), ("u2", "submission_unconfirmed"),
                        ("u3", "already_applied"), ("u4", "scored")):
        conn.execute(
            "INSERT INTO jobs (url, company, title, description, status, qual_decision, qual_confidence, "
            "qual_version, qual_evidence) VALUES (?, 'Co', 'Software Engineer', ?, ?, ?, ?, ?, ?)",
            (url, PAD + STACK, status, *snapshot))
    conn.commit()
    conn.row_factory = sqlite3.Row
    updates = cleanup_backlog.plan_changes(CFG, conn)
    protected = {u["url"] for u in updates if not QUAL_COLUMNS <= set(u)}
    assert protected == {"u2", "u3"}  # u1 is excluded by the query; u2/u3 carry no qual_* keys
    cleanup_backlog.apply_updates(conn, updates)
    rows = {r["url"]: tuple(r[c] for c in sorted(QUAL_COLUMNS))
            for r in conn.execute("SELECT * FROM jobs")}
    original = tuple(dict(zip(("qual_decision", "qual_confidence", "qual_version", "qual_evidence"),
                              snapshot))[c] for c in sorted(QUAL_COLUMNS))
    assert rows["u1"] == rows["u2"] == rows["u3"] == original
    assert rows["u4"] != original


# --- Replay script (read-only) ----------------------------------------------------------------

def test_replay_script_is_read_only_and_writes_jsonl(temp_db, tmp_path, monkeypatch):
    import qualification_replay
    conn = temp_db.get_conn()
    conn.execute("INSERT INTO jobs (url, company, title, description, status, status_reason) "
                 "VALUES ('r1', 'Co', 'Java Developer', ?, 'filtered', 'excluded_role:stack_mismatch:java')",
                 (PAD + "Requirements:\n- 3+ years of Java\n",))
    conn.commit()
    conn.close()
    ro = qualification_replay.open_readonly(temp_db.DB_PATH)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("UPDATE jobs SET title = 'x'")
    ro.close()
    out = tmp_path / "out.jsonl"
    monkeypatch.setattr(sys, "argv", ["qualification_replay", "--db", str(temp_db.DB_PATH),
                                      "--statuses", "filtered", "--out", str(out)])
    qualification_replay.main()
    record = json.loads(out.read_text().splitlines()[0])
    assert {"id", "old_status", "old_reason", "old_tier", "new_decision", "new_tier", "confidence",
            "fit_score", "required_years", "reasons"} <= set(record)
    assert record["new_decision"] == "rejected"


# --- Round 2: targeted error classes ---------------------------------------------------------

def test_markdown_emphasis_experience_header_overall_figure_beats_per_skill():
    desc = PAD + ("**Experience**\n\n* **5–8+ years** of software/AI/ML engineering experience.\n"
                  "* **2–3+ years** of LLM application development.\n\n**Requirements**\n* Python, React\n")
    q = qualify("AI Engineer", desc, CFG)
    assert q.required_years == 5 and q.decision == "rejected"
    assert q.reasons[0].startswith("seniority:years:5")


def test_min_experience_key_value_line_is_the_overall_figure():
    desc = PAD + "**Min Experience:** 4+ years\n* 2 years of React\n" + STACK
    q = qualify("Software Engineer", desc, CFG)
    assert q.required_years == 4 and q.decision == "qualified" and q.tier == STRETCH
    q = qualify("Software Engineer", PAD + "Experience required: 6 years\n" + STACK, CFG)
    assert q.required_years == 6 and q.decision == "rejected"


@pytest.mark.parametrize("line", [
    "Business-level English; German is a major plus.", "English fluent, French is an advantage",
    "Fluent English. Fluent German would be a bonus.", "Spanish preferred, English required",
])
def test_language_marked_as_plus_is_not_required(line):
    desc = PAD + STACK + line + "\n"
    q = qualify("Software Engineer", desc, CFG)
    assert q.decision == "qualified", q.reasons


def test_fluent_german_c1_stays_decisive():
    q = qualify("Software Engineer", PAD + STACK + "Fluent in German (C1) and English\n", CFG)
    assert q.decision == "rejected" and "language_required:german" in q.reasons[0]


@pytest.mark.parametrize("title", ["Lead MERN Stack Developer / Technology Lead", "Full Stack Lead Developer"])
def test_lone_lead_title_is_review_and_corroborated_by_three_years(title):
    assert qualify(title, PAD + STACK, CFG).decision == "review"
    q = qualify(title, PAD + STACK + "- 3+ years of experience\n", CFG)
    assert q.decision == "rejected" and q.reasons[0].startswith("seniority:")


def test_senior_with_three_years_stays_stretch_and_lead_with_low_years_wins():
    q = qualify("Senior Backend Engineer", PAD + STACK + "- 3+ years of experience\n", CFG)
    assert q.decision == "qualified" and q.tier == STRETCH
    q = qualify("Lead Developer", PAD + "Requirements:\n- 1-2 years of experience\n- Python\n", CFG)
    assert q.decision == "qualified"


@pytest.mark.parametrize("title", ["Remote Software Engineer - Rust", "Fullstack Blockchain Developer",
                                   "Software Engineer (Java)"])
def test_absent_stack_token_anywhere_in_title_is_role_identity(title):
    q = qualify(title, "Build things.", CFG)
    assert q.decision == "review" and q.reasons[0].startswith("stack:title_role:")


def test_absent_token_in_title_with_core_token_stays_secondary():
    q = qualify("Senior Full Stack Engineer - Android + Go/Java", PAD + STACK, CFG)
    assert q.decision == "qualified"
    assert any(s.detail.startswith("title_secondary:") for s in q.signals)


@pytest.mark.parametrize("title", ["DevOps / Platform Engineer", "MLOps Engineer", "Cloud Engineer",
                                   "Site Reliability Engineer", "Data Engineer"])
def test_role_type_titles_are_identity_wherever_they_appear(title):
    q = qualify(title, PAD + STACK, CFG)
    assert q.decision == "review" and "title_role:" in q.reasons[0]


def test_data_engineer_with_spark_airflow_requirements_is_rejected():
    desc = PAD + "Requirements:\n- Apache Spark, Airflow and Databricks\n- SQL\n"
    q = qualify("Data Engineer II", desc, CFG)
    assert q.decision == "rejected" and "title_role:data engineer" in q.reasons[0]


def test_content_production_duties_do_not_end_core_qualified():
    desc = PAD + ("Requirements:\n- 2 years of experience\n- Create short-form video content for social\n"
                  "- Python\n")
    q = qualify("AI Content Engineer", desc, CFG)
    assert q.decision != "rejected" and q.tier != CORE
    assert any(s.detail.startswith("non_engineering_duties") for s in q.signals)


# --- Round 3 ---------------------------------------------------------------------------------

def test_passing_future_opportunities_mention_is_not_a_talent_pool_posting():
    desc = PAD + STACK + "High-performing candidates may be considered for future opportunities as the company grows.\n"
    assert qualify("Full Stack Developer", desc, CFG).decision == "qualified"


@pytest.mark.parametrize("title,line", [
    ("Software Engineer - Future Opportunities", ""), ("Open Application - Engineering", ""),
    ("Software Engineer", "This is not an open position; join our talent community."),
    ("Software Engineer", "There is no current opening. Submit your profile for future roles."),
])
def test_posting_level_talent_pool_phrasing_is_rejected(title, line):
    q = qualify(title, PAD + STACK + line + "\n", CFG)
    assert q.decision == "rejected" and "non_job:talent_pool" in q.reasons[0]


def test_llm_application_title_and_duties_count_as_core_evidence():
    desc = PAD + ("Requirements:\n- Experience building AI-powered workflows and agents\n"
                  "- Familiarity with Salesforce integrations\n")
    q = qualify("AI Engineer", desc, CFG)
    assert q.decision != "rejected", q.reasons
    desc = PAD + "You will build agents and LLM pipelines.\nRequirements:\n- Salesforce APIs\n"
    assert qualify("Agentic Developer", desc, CFG).decision != "rejected"


def test_company_and_investor_names_are_not_stack():
    desc = PAD + STACK + "We are backed by Spark Capital, Rust Ventures and Unity Partners.\n"
    q = qualify("Software Engineer", desc, CFG)
    assert q.decision == "qualified" and not any("spark" in s.detail or "rust" in s.detail for s in q.signals)


def test_devops_intern_with_tooling_duties_is_not_no_dev_evidence():
    desc = PAD + ("Experience: 0-1 year\nResponsibilities:\n* Maintain Git and GitHub workflows\n"
                  "* Build Docker images and CI/CD pipelines on Linux\n* Shell scripting for deployments\n")
    q = qualify("DevOps Intern / Fresher", desc, CFG)
    assert q.decision != "rejected", q.reasons
    assert all("no_dev_evidence" not in s.detail for s in q.signals)


def test_junior_title_downgrades_role_identity_but_paid_program_still_rejects():
    desc = PAD + STACK + "Experience: 0-1 year\n"
    for title in ("Cloud Engineer Intern", "Junior Data Engineer", "SRE Trainee", "DevOps Fresher"):
        q = qualify(title, desc, CFG)
        assert q.decision == "qualified", (title, q.reasons)
        assert any(s.detail.startswith("title_secondary:") for s in q.signals)
    paid = qualify("DevOps Intern", desc + "Course fee: Rs 10,000 for the training program.\n", CFG)
    assert paid.decision == "rejected" and "non_job:paid_program" in paid.reasons[0]


@pytest.mark.parametrize("title", ["Manager, Engineering, Git & Gitaly Operations", "Manager - Engineering",
                                   "Engineering Manager", "Manager, Software Engineering"])
def test_engineering_manager_forms_are_policy_rejected(title):
    assert classify_tier(title, PAD + STACK, CFG)[2] == "excluded_role:people_management"
    assert not passes_filters({"title": title, "description": PAD + STACK, "location": "Remote, India"}, CFG)[0]


def test_product_manager_is_still_handled_by_non_engineering_title_rule():
    assert classify_tier("Product Manager", PAD, CFG)[2] == "excluded_role:non_engineering_title"


# --- Round 4: regressions vs the old gate -----------------------------------------------------

@pytest.mark.parametrize("title,years", [
    ("Automation Technical Architect- 10-15 Yrs Relevant Experience", 10),
    ("Backend Developer - 6+ Years Exp", 6), ("Python Developer (min 5year)", 5)])
def test_years_in_title_are_decisive(title, years):
    q = qualify(title, PAD + STACK, CFG)
    assert q.decision == "rejected" and q.required_years == years
    assert q.reasons[0].startswith("seniority:years:")


def test_fallback_years_at_least_five_are_review_alone_and_reject_with_senior_title():
    q = qualify("Software Engineer", PAD + "Python and React.\nWe offer 8 years of growth.\n", CFG)
    assert q.required_years == 8 and q.decision == "review" and q.tier == STRETCH
    q = qualify("Senior Software Engineer", PAD + "Python and React.\nWe offer 8 years of growth.\n", CFG)
    assert q.decision == "rejected" and "years:8:fallback" in q.reasons[0]


def test_tier_is_never_core_when_any_source_years_exceed_core_max():
    q = qualify("Software Engineer", PAD + "Python and React.\nA 3 year roadmap awaits.\n", CFG)
    assert q.required_years == 3 and q.tier == STRETCH


@pytest.mark.parametrize("title", [
    "Data Scientist", "Senior Data Scientist", "Machine Learning Engineer",
    "Machine Learning Engineer — Distillation", "Software Engineer, Machine Learning", "Senior ML Engineer"])
def test_ml_training_titles_are_role_identity_even_with_llm_mentions_in_description(title):
    desc = PAD + "Requirements:\n- Python\n- Exposure to LLM and RAG systems\n"
    q = qualify(title, desc, CFG)
    assert q.decision in ("review", "rejected"), (title, q.reasons)
    assert any(s.detail.startswith("title_role:") and s.dimension == "stack" for s in q.signals)


def test_llm_terms_in_title_neutralise_ml_title_tokens():
    assert qualify("Machine Learning Engineer, LLM Applications", PAD + STACK, CFG).decision == "qualified"
    assert qualify("Applied AI Engineer", PAD + STACK, CFG).decision == "qualified"


def test_training_phrases_in_requirements_corroborate_ml_title_to_reject():
    desc = PAD + "Requirements:\n- Experience with model distillation and pretraining optimization\n- Python\n"
    q = qualify("Machine Learning Engineer — Distillation", desc, CFG)
    assert q.decision == "rejected" and "desc_required" in q.reasons[0]


def test_strong_required_signal_is_not_halved_by_positive_fit():
    desc = PAD + "Requirements:\n- 3+ years of Ruby on Rails\n- React, TypeScript, PostgreSQL\n"
    q = qualify("Full-Stack Engineer (Ruby on Rails/ReactJS)", desc, CFG)
    assert q.decision == "rejected" and "desc_required:ruby on rails" in q.reasons[0]
    assert qualify("Full Stack Engineer (AWS)", PAD + STACK, CFG).decision == "qualified"
    lone = qualify("Software Engineer", PAD + "Requirements:\n- 5 years of Ruby on Rails\n- React\n", CFG)
    assert lone.decision == "rejected" and lone.required_years == 5


@pytest.mark.parametrize("title", [
    "Sr. Engagement Manager, Forward Deployed Engineering", "Software Publisher Services – Manager",
    "Manager of Platform Engineering", "Delivery - Manager"])
def test_standalone_manager_titles_are_people_management(title):
    assert classify_tier(title, PAD + STACK, CFG)[2] == "excluded_role:people_management"


def test_manager_inside_product_name_and_pm_titles_keep_their_reasons():
    assert classify_tier("Package Manager Engineer", PAD + STACK, CFG)[0] is not None
    for title in ("Product Manager", "Project Manager", "Program Manager - Engineering"):
        assert classify_tier(title, PAD, CFG)[2] == "excluded_role:non_engineering_title"


@pytest.mark.parametrize("title", [
    "Software Engineer in Test", "Software Development Engineer in Test", "Senior Software Engineer in Test",
    "QA ENGINEERING (AUTOMATIONS)", "Senior QA & Automation Engineer"])
def test_qa_titles_are_policy_rejected(title):
    assert classify_tier(title, PAD + STACK, CFG)[2] == "excluded_role:qa_only"


def test_plain_automation_engineer_stays_engineering():
    assert classify_tier("Automation Engineer", PAD + STACK, CFG)[0] is not None


# --- Round 5 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "**Required Skills:** * 5+ yrs of proficiency in Python (especially FastAPI and asyncio)",
    "Required Skills:\n* 5+ years of hands-on Python\n* React", "Requirements:\n* 5 years working with Python",
    "Requirements:\n* Python: 5 years (Required)"])
def test_per_skill_years_phrasings_parse_and_reject_senior_title(line):
    q = qualify("Senior SWE - Python / TypeScript", PAD + line + "\n", CFG)
    assert q.required_years == 5 and q.decision == "rejected", q.reasons


def test_preferred_per_skill_years_are_ignored():
    q = qualify("Senior SWE", PAD + "Requirements:\n* React, Python\n* Python: 5 years (Preferred)\n", CFG)
    assert q.required_years is None and q.decision == "qualified"


@pytest.mark.parametrize("line", ["1–2 years of experience in Android application development",
                                  "Android Development: 1 year (Required)"])
def test_academic_stack_with_low_years_is_allowed_but_stretch(line):
    q = qualify("Mobile Developer", PAD + f"Requirements:\n* {line}\n* Kotlin\n", CFG)
    assert q.decision == "qualified" and q.tier == STRETCH, q.reasons


def test_junior_title_with_academic_stack_may_stay_core():
    q = qualify("Android Developer Intern", PAD + PAD + "Requirements:\n* Kotlin and Android basics\n", CFG)
    assert q.decision == "qualified" and q.tier == CORE


def test_cloud_developer_and_architect_titles_are_role_identity():
    desc = PAD + "Requirements:\n* Python\n* 3 years of Azure, Fabric and Purview\n"
    q = qualify("Senior Cloud Developer (Python/Azure/Fabric/Purview)", desc, CFG)
    assert q.decision != "qualified", q.reasons
    assert qualify("Cloud Architect", PAD + STACK, CFG).decision != "qualified"
