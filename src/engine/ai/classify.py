"""Scoring/classification role — AI_SYSTEM.md §22-26.

Target baseline: Phi-4-mini. Structured, bounded judgment — score (1-10),
confidence, a concise reason, and risk flags (§23 Score Output). The model
cannot create new policy states (§23); this module's caller (not this
module) is responsible for mapping the score into workflow semantics.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import gateway
from .embed import candidate_text

PROMPT_SCHEMA_VERSION = "classify_v1"

SCORE_SYSTEM = (
    "You are a strict technical recruiter. Rate how likely this candidate gets an "
    "interview for the job, using ONLY the fact sheet below. Output JSON only, no "
    "other text:\n"
    '{"score": <int 1-10>, "confidence": <float 0-1>, "reason": "<max 20 words>", '
    '"risk_flags": [<zero or more short strings, e.g. "experience_gap", "no_published_salary">]}\n'
    "9-10: stack and seniority match closely, no material gap. "
    "6-8: most required skills match, acceptable experience gap. "
    "1-5: needs a skill, degree, or years the candidate's fact sheet does not show."
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?|```")


@dataclass(frozen=True)
class ScoreResult:
    score: float
    confidence: float
    reason: str
    risk_flags: list[str] = field(default_factory=list)
    model: str = ""
    prompt_version: str = PROMPT_SCHEMA_VERSION
    latency_seconds: float = 0.0


def _build_prompt(title: str, description: str, location: str) -> str:
    return (
        f"FACT SHEET:\n{candidate_text()}\n\n"
        f"JOB:\nTitle: {title}\nLocation: {location}\nDescription: {(description or '')[:1800]}"
    )


def _parse(response: str) -> dict:
    cleaned = _JSON_BLOCK_RE.sub("", response).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed scoring JSON: {response[:200]}") from exc
    if "score" not in data:
        raise ValueError(f"scoring response missing 'score' field: {response[:200]}")
    return data


def _validate(data: dict) -> ScoreResult:
    """AI_SYSTEM.md §59 Output Parsing: enforce expected fields, value
    ranges, types. Malformed output must not be accepted as truth."""
    score = float(data["score"])
    if not (1 <= score <= 10):
        raise ValueError(f"score {score} outside 1-10 range")
    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason", ""))[:200]
    risk_flags = data.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = []
    risk_flags = [str(f)[:60] for f in risk_flags][:10]
    return ScoreResult(score=score, confidence=confidence, reason=reason, risk_flags=risk_flags)


def score_job(title: str, description: str, location: str = "") -> ScoreResult:
    """Raises gateway.AIUnavailable / gateway.AITimeout on infra failure,
    ValueError on malformed/out-of-range model output (caller decides
    retry/fallback per AI_SYSTEM.md §80/§81)."""
    prompt = _build_prompt(title, description, location)
    result = gateway.chat("scoring", prompt, system=SCORE_SYSTEM, temperature=0.1,
                           json_mode=True, max_tokens=150)
    parsed = _validate(_parse(result.content))
    cfg_model = gateway.load_role_config().model_for("scoring")
    return ScoreResult(
        score=parsed.score, confidence=parsed.confidence, reason=parsed.reason,
        risk_flags=parsed.risk_flags, model=cfg_model, latency_seconds=result.latency_seconds,
    )
