"""Role -> model configuration. AI_SYSTEM.md §4 Role Architecture:

    Embedding              -> Nomic embedding model
    Semantic reranking     -> BGE-class reranker
    Scoring/classification -> Phi-4-mini scoring/classification specialist
    Generation              -> Qwen3.5-4B generation specialist

"The model family/role is architectural. The exact checkpoint is an
implementation choice until benchmarked on the real host" (§4) — so the
exact Ollama tags below are this implementation's choice, read from
config.yaml's `ai_roles` block (new, additive key; distinct from the
legacy `llm:` block src/llm.py reads) with these as defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent.parent.parent

# Defaults match what was actually pulled onto this host for Phase 4 — see
# the Phase 4 report for `ollama list` output and why each was chosen.
DEFAULT_ROLES = {
    "embedding": "nomic-embed-text",
    "reranker": "dengcao/bge-reranker-v2-m3",
    "scoring": "phi4-mini",
    "generation": "qwen3.5:4b-q4_K_M",
}

DEFAULTS = {
    "base_url": "http://localhost:11434",
    "timeout": 180,
    "keep_alive": "30m",
    "roles": DEFAULT_ROLES,
}


@dataclass(frozen=True)
class RoleConfig:
    base_url: str
    timeout: int
    keep_alive: str
    roles: dict[str, str]

    def model_for(self, role: str) -> str:
        return self.roles[role]


@lru_cache(maxsize=1)
def load_role_config() -> RoleConfig:
    cfg = yaml.safe_load(open(ROOT / "config.yaml")) or {}
    ai_cfg = cfg.get("ai_roles") or {}
    roles = {**DEFAULT_ROLES, **(ai_cfg.get("roles") or {})}
    return RoleConfig(
        base_url=ai_cfg.get("base_url", DEFAULTS["base_url"]),
        timeout=ai_cfg.get("timeout", DEFAULTS["timeout"]),
        keep_alive=ai_cfg.get("keep_alive", DEFAULTS["keep_alive"]),
        roles=roles,
    )
