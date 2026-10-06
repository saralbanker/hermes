"""Embedding role — AI_SYSTEM.md §12-18.

Candidate representation (§13) derives from profile/facts.md, read
independently here (own file I/O — this module stays isolated from
src/llm.py per the Phase 4 brief, rather than importing its `facts()`).
Job representation (§14) is a normalized subset of job fields, not raw HTML.
Every cache entry carries model + input hash + representation version (§15/§16).
"""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

from . import gateway
from .roles import load_role_config

ROOT = Path(__file__).parent.parent.parent.parent
FACTS_PATH = ROOT / "profile" / "facts.md"
REPRESENTATION_VERSION = "v1"

# Dependency-free import of project_registry (src/project_registry.py), without importing
# src/llm.py — this module stays isolated from llm.py per the Phase 4 brief (own file I/O
# below), but must derive the SAME retired-project redaction llm.py uses.
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from project_registry import redact_retired_sections  # noqa: E402


def candidate_text() -> str:
    """§13 Candidate Representation: profile/facts.md only — no OTPs, no
    mailbox contents, no speculative/unverified claims (those were never in
    facts.md to begin with, by construction of that file). Retired-project
    sections are redacted via project_registry.redact_retired_sections (same
    registry src/llm.py's facts() uses), which fails closed on any delimiter
    drift rather than risk a retired project leaking into an LLM prompt."""
    return redact_retired_sections(FACTS_PATH.read_text(encoding="utf-8"))


def job_text(title: str, description: str, location: str = "", work_mode: str = "",
             salary_text: str = "") -> str:
    """§14 Job Representation: title + bounded description + requirements/
    responsibilities implicitly inside description + location/work mode +
    salary where present. Not unlimited raw HTML — callers must pass
    already-normalized text, and this function itself still bounds length."""
    parts = [title or "", (description or "")[:2000]]
    if location:
        parts.append(f"Location: {location}")
    if work_mode:
        parts.append(f"Work mode: {work_mode}")
    if salary_text:
        parts.append(f"Salary: {salary_text}")
    return "\n".join(p for p in parts if p)


def input_hash(text: str) -> str:
    """§15 Representation Versioning: identifies the exact embedded input."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(text: str) -> str:
    """§16 Embedding Cache: model + input hash + representation version."""
    model = load_role_config().model_for("embedding")
    return f"{model}::{REPRESENTATION_VERSION}::{input_hash(text)}"


def embed_batch(texts: list[str], prefix: str = "") -> tuple[list[list[float]], float]:
    """§65 Embedding Batching: one HTTP call for the whole batch.
    `prefix` supports nomic-embed-text's documented search_query:/
    search_document: instruction prefixes."""
    prefixed = [f"{prefix}{t}" for t in texts] if prefix else texts
    return gateway.embed(prefixed)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
