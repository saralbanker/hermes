"""
llm.py — Single local-LLM client for every Hermes stage (Ollama HTTP API).

Why one module: score/tailor/apply each had their own copy of call_qwen with
different error handling. A missing model returns HTTP 404, which the old
copies did not catch — the daily run crashed at SCORE for 10+ days in Sep 2026.
Here every failure mode raises LLMUnavailable, which callers treat as
"use the deterministic fallback".
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import requests
import yaml

from project_registry import redact_retired_sections

ROOT = Path(__file__).parent.parent
FACTS_PATH = ROOT / "profile" / "facts.md"

DEFAULTS = {
    "base_url": "http://localhost:11434",
    "model": "qwen3:4b-instruct-2507-q4_K_M",
    "embed_model": "nomic-embed-text",
    "timeout": 180,
    "keep_alive": "30m",
}


class LLMUnavailable(RuntimeError):
    """Ollama unreachable, model missing, timeout, or malformed response."""


@lru_cache(maxsize=1)
def llm_config() -> dict:
    cfg = yaml.safe_load(open(ROOT / "config.yaml"))
    return {**DEFAULTS, **(cfg.get("llm") or {})}


def facts_full() -> str:
    """Unredacted — audit/human tooling ONLY. Never pass to an LLM prompt."""
    return FACTS_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)   # existing decorator, unchanged position
def facts() -> str:
    """The verified fact sheet, retired-project sections redacted — the only candidate
    facts an LLM may use. See project_registry.redact_retired_sections: fails closed
    (raises FactsRedactionError) if facts.md's RETIRED delimiters drift from the
    registry, rather than ever risking a retired project leaking into an LLM prompt."""
    return redact_retired_sections(facts_full())


def chat(prompt: str, system: str = "", temperature: float = 0.3,
         json_mode: bool = False, max_tokens: int = 600) -> str:
    c = llm_config()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    body = {
        "model": c["model"],
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": c["keep_alive"],
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192},
    }
    if json_mode:
        body["format"] = "json"
    try:
        resp = requests.post(f"{c['base_url']}/api/chat", json=body, timeout=c["timeout"])
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise LLMUnavailable(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


def embed(texts: list[str]) -> list[list[float]]:
    c = llm_config()
    try:
        resp = requests.post(
            f"{c['base_url']}/api/embed",
            json={"model": c["embed_model"], "input": texts, "keep_alive": c["keep_alive"]},
            timeout=c["timeout"],
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise LLMUnavailable(f"embed failed: {str(exc)[:200]}") from exc


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def installed_models() -> list[str]:
    c = llm_config()
    try:
        resp = requests.get(f"{c['base_url']}/api/tags", timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise LLMUnavailable(f"Ollama not reachable: {exc}") from exc


def is_ready() -> bool:
    """True when Ollama is up and both configured models are installed."""
    c = llm_config()
    try:
        names = installed_models()
    except LLMUnavailable:
        return False
    def has(model: str) -> bool:
        return any(n == model or n == f"{model}:latest" for n in names)
    return has(c["model"]) and has(c["embed_model"])
