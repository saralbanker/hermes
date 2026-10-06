"""AI Gateway — AI_SYSTEM.md §7: the only module that speaks raw Ollama HTTP.

    embed(texts)
    rerank(query, documents)
    classify(input, schema)   -> generate.py/classify.py build the prompt; this
    generate(input, constraints)  module just executes the HTTP call + failure mapping
    health(role)
    load(role) / unload(role)

Every failure mode raises a typed exception (mirrors src/llm.py's
LLMUnavailable pattern, AI_SYSTEM.md §78: "the legacy llm.py centralized
this concept as LLMUnavailable and that semantic behavior should remain" —
kept as a *pattern* to reuse, not by importing llm.py itself, since this is
a separate, isolated pipeline per the Phase 4 brief).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

from .roles import RoleConfig, load_role_config


class AIUnavailable(RuntimeError):
    """Ollama unreachable, or the model for this role is not installed.
    AI_SYSTEM.md §77/§78: Runtime Unavailable / Missing Model."""


class AITimeout(RuntimeError):
    """AI_SYSTEM.md §79: model call exceeded its bounded timeout."""


@dataclass(frozen=True)
class CallResult:
    content: str
    latency_seconds: float


def _post(path: str, body: dict, cfg: RoleConfig) -> tuple[dict, float]:
    start = time.monotonic()
    try:
        resp = requests.post(f"{cfg.base_url}{path}", json=body, timeout=cfg.timeout)
        resp.raise_for_status()
        return resp.json(), time.monotonic() - start
    except requests.Timeout as exc:
        raise AITimeout(f"{path} exceeded {cfg.timeout}s: {exc}") from exc
    except (requests.RequestException, ValueError) as exc:
        raise AIUnavailable(f"{path} failed: {type(exc).__name__}: {str(exc)[:200]}") from exc


def chat(role: str, prompt: str, system: str = "", temperature: float = 0.3,
         json_mode: bool = False, max_tokens: int = 600, num_ctx: int = 8192) -> CallResult:
    """Role-addressed chat completion (used by classify.py and generate.py)."""
    cfg = load_role_config()
    model = cfg.model_for(role)
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    body = {
        "model": model, "messages": messages, "stream": False, "think": False,
        "keep_alive": cfg.keep_alive,
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx},
    }
    if json_mode:
        body["format"] = "json"
    data, latency = _post("/api/chat", body, cfg)
    try:
        return CallResult(data["message"]["content"].strip(), latency)
    except (KeyError, TypeError) as exc:
        raise AIUnavailable(f"malformed /api/chat response: {str(data)[:200]}") from exc


def embed(texts: list[str]) -> tuple[list[list[float]], float]:
    """AI_SYSTEM.md §12/§65: embedding role, batched. Returns (vectors, latency_seconds)."""
    cfg = load_role_config()
    body = {"model": cfg.model_for("embedding"), "input": texts, "keep_alive": cfg.keep_alive}
    data, latency = _post("/api/embed", body, cfg)
    try:
        return data["embeddings"], latency
    except KeyError as exc:
        raise AIUnavailable(f"malformed /api/embed response: {str(data)[:200]}") from exc


def installed_models() -> list[str]:
    cfg = load_role_config()
    try:
        resp = requests.get(f"{cfg.base_url}/api/tags", timeout=10)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise AIUnavailable(f"Ollama not reachable: {exc}") from exc


def running_models() -> list[dict]:
    """`ollama ps` equivalent (/api/ps) — used by resource_arbiter.py to read
    actual loaded-model RSS (AI_SYSTEM.md §101 "RSS where measurable")."""
    cfg = load_role_config()
    try:
        resp = requests.get(f"{cfg.base_url}/api/ps", timeout=10)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except (requests.RequestException, ValueError) as exc:
        raise AIUnavailable(f"Ollama not reachable: {exc}") from exc


def health(role: str) -> dict:
    """AI_SYSTEM.md §101 AI Health: available/unavailable + installed model."""
    cfg = load_role_config()
    model = cfg.model_for(role)
    try:
        names = installed_models()
    except AIUnavailable as exc:
        return {"role": role, "model": model, "available": False, "reason": str(exc)}
    installed = any(n == model or n == f"{model}:latest" for n in names)
    return {"role": role, "model": model, "available": installed,
            "reason": None if installed else "model not installed"}


def unload(role: str) -> None:
    """AI_SYSTEM.md §7 load/unload: set keep_alive=0 to release the model's
    RAM immediately (AI_SYSTEM.md §82 Resource Exhaustion: "release/unload
    model")."""
    cfg = load_role_config()
    model = cfg.model_for(role)
    try:
        requests.post(f"{cfg.base_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
    except requests.RequestException:
        pass  # best-effort; an unload failure is not itself an AI failure
