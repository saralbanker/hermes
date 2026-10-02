"""Generation role — AI_SYSTEM.md §28-42.

Target baseline: Qwen3.5-4B. Reuses tailor.py's existing honesty/validation
machinery (fact-boundary enforcement, number-safety, project-attribution
checks, resume-variant selection, the fixed closing paragraph, the
deterministic fallback template) rather than reimplementing it — the Phase 4
brief is explicit that this part should not be reinvented. Only the model
call itself goes through the new gateway (Qwen3.5-4B) instead of
src/llm.py's chat() (the legacy Qwen3 4B-instruct model); tailor.py itself
is never imported in a way that calls llm.chat — only its pure validation/
data functions are reused.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import tailor as _tailor  # noqa: E402 — pure helper functions only, never _llm_body/generate_cover_letter

from . import gateway
from .embed import candidate_text

PROMPT_SCHEMA_VERSION = "generate_v1"

GENERATION_SYSTEM = (
    "You write the first two paragraphs of a cover letter for the candidate, first person.\n"
    "STRICT RULES: use ONLY facts from the FACT SHEET. Do not invent experience, employers, "
    "domains, metrics, or percentages. Do not claim a skill unless it is in the fact sheet. "
    "If the job needs something the candidate lacks, do not mention it.\n"
    "Paragraph 1 (2 sentences): what specifically about this role or company fits the "
    "candidate's real work. Paragraph 2 (2-3 sentences): the single most relevant project "
    "from the fact sheet, with its real numbers. No greeting, no sign-off, no lists. "
    "Max 120 words total."
)


@dataclass(frozen=True)
class GenerationResult:
    letter: str
    source: str  # "llm" or "template" (AI_SYSTEM.md §42 Deterministic Generation Fallback)
    model: str
    attempts: int
    latency_seconds: float


def select_resume_variant(title: str, description: str) -> str:
    return _tailor.select_resume_variant(title, description)


def _llm_body(job: dict, focus_keywords: list[str], feedback: str) -> tuple[str, float]:
    prompt = (
        f"FACT SHEET:\n{candidate_text()}\n\nJOB:\nCompany: {job['company']}\nTitle: {job['title']}\n"
        f"Relevant keywords: {', '.join(focus_keywords[:8])}\n"
        f"Description: {(job.get('description') or '')[:1500]}\n{feedback}"
    )
    result = gateway.chat("generation", prompt, system=GENERATION_SYSTEM, temperature=0.4, max_tokens=260)
    return result.content.strip(), result.latency_seconds


def generate_cover_letter(job: dict, focus_keywords: list[str], variant: str) -> GenerationResult:
    """§41 Generation Retry: one bounded retry with deterministic feedback on
    validation failure. §42 Deterministic Generation Fallback: two failed
    attempts (or AI unavailable) -> tailor.py's existing fact-only template,
    never a third model call."""
    model = gateway.load_role_config().model_for("generation")
    feedback = ""
    total_latency = 0.0
    for attempt in range(1, 3):
        try:
            body, latency = _llm_body(job, focus_keywords, feedback)
        except (gateway.AIUnavailable, gateway.AITimeout):
            break
        total_latency += latency
        problems = _tailor.validate_letter(body)
        if not problems:
            letter = f"{body}\n\n{_tailor.CLOSING}"
            return GenerationResult(letter, "llm", model, attempt, total_latency)
        feedback = "\nYOUR PREVIOUS DRAFT WAS REJECTED: " + "; ".join(problems) + ". Fix it."
    template = _tailor.template_letter(job, variant)
    return GenerationResult(template, "template", model, 2, total_latency)
