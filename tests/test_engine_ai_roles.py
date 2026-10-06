"""Phase 4: src/engine/ai/roles.py — role -> model config loading."""
from __future__ import annotations

from engine.ai import roles


def test_default_roster_matches_ai_system_role_architecture():
    """AI_SYSTEM.md §4: Nomic embedding, BGE-class reranker, Phi-4-mini
    scoring, Qwen3.5-4B generation."""
    assert "nomic" in roles.DEFAULT_ROLES["embedding"].lower()
    assert "bge" in roles.DEFAULT_ROLES["reranker"].lower()
    assert "phi4" in roles.DEFAULT_ROLES["scoring"].lower()
    assert "qwen3.5" in roles.DEFAULT_ROLES["generation"].lower()


def test_load_role_config_reads_config_yaml():
    roles.load_role_config.cache_clear()
    cfg = roles.load_role_config()
    assert cfg.base_url.startswith("http")
    assert cfg.timeout > 0
    for role in ("embedding", "reranker", "scoring", "generation"):
        assert cfg.model_for(role)


def test_role_config_is_isolated_from_legacy_llm_config():
    """config.yaml's `llm:` block (read by src/llm.py) and `ai_roles:`
    block (read here) must be independent — this is the whole point of a
    separate pipeline."""
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load(open(Path(roles.ROOT) / "config.yaml"))
    assert "llm" in cfg
    assert "ai_roles" in cfg
    assert cfg["llm"]["model"] != cfg["ai_roles"]["roles"]["generation"]
