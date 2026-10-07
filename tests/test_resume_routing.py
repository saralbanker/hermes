"""Resume variant routing: the title decides; the description only breaks ties on generic titles."""
import pytest

from tailor import select_resume_variant

AI_DESC = "We build products with AI everywhere. Join our AI-first team."  # incidental, no strong signal


@pytest.mark.parametrize("title, expected", [
    ("Full Stack Developer", "fullstack"),
    ("Senior Full Stack Developer", "fullstack"),
    ("Front End Developer Intern", "fullstack"),
    ("Front End Developer", "fullstack"),
    ("Frontend Engineer", "fullstack"),
    ("Front-End Developer", "fullstack"),
    ("React Developer", "fullstack"),
    ("Next.js Engineer", "fullstack"),
    ("MERN Stack Developer", "fullstack"),
    ("Web Developer", "fullstack"),
    ("Node js developer", "backend"),
    ("Node.js Engineer", "backend"),
    ("Backend Engineer", "backend"),
    ("Back End Developer", "backend"),
    ("Golang Developer", "backend"),
    ("Python Developer", "backend"),
    ("API Engineer", "backend"),
    ("Platform Engineer", "backend"),
    ("Senior DevOps Engineer", "backend"),
    ("AI Engineer", "ai"),
    ("LLM Engineer", "ai"),
    ("RAG Developer", "ai"),
    ("GenAI Developer", "ai"),
    ("Machine Learning Engineer", "ai"),
    ("Full Stack Engineer - AI", "ai"),          # mixed: ai outranks fullstack
    ("Full Stack Node.js Developer", "fullstack"),  # mixed: fullstack outranks backend
])
def test_title_decides_even_when_description_mentions_ai(title, expected):
    assert select_resume_variant(title, AI_DESC) == expected


@pytest.mark.parametrize("title", ["PHP Laravel Developer", "Software Engineer"])
def test_generic_title_with_incidental_ai_mention_is_not_ai(title):
    assert select_resume_variant(title, AI_DESC) != "ai"


def test_generic_title_one_weak_term_is_not_ai():
    assert select_resume_variant("Software Engineer", "Our product uses AI to rank results.") == "fullstack"


@pytest.mark.parametrize("desc", [
    "You will build LLM-powered features.",
    "Experience with RAG pipelines and embeddings.",
    "Work on GenAI products.",
    "Hands-on with AI and machine learning models.",   # two distinct weak terms
])
def test_generic_title_strong_ai_signal_is_ai(desc):
    assert select_resume_variant("Software Engineer", desc) == "ai"


def test_generic_title_backend_description_is_backend():
    desc = "Design REST APIs and microservices in Python and Go; distributed systems experience."
    assert select_resume_variant("Software Engineer", desc) == "backend"


def test_generic_title_frontend_description_is_fullstack():
    assert select_resume_variant("Software Engineer", "React and TypeScript UI work.") == "fullstack"


def test_generic_title_empty_description_defaults_fullstack():
    assert select_resume_variant("Software Engineer", "") == "fullstack"
    assert select_resume_variant("Software Engineer", None) == "fullstack"  # type: ignore[arg-type]
