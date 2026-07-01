#!/usr/bin/env python3
"""
switch_mode.py — One-command model/inference mode switcher.

Usage:
  python scripts/switch_mode.py local            # Ollama + local Qwen (default)
  python scripts/switch_mode.py cloud            # Claude CLI for apply
  python scripts/switch_mode.py keyword-only     # No LLM at all

  python scripts/switch_mode.py model score qwen3:4b    # change score model
  python scripts/switch_mode.py model tailor qwen3:4b   # change tailor model
  python scripts/switch_mode.py model apply qwen2.5:3b  # change apply model

  python scripts/switch_mode.py status           # show current settings
"""
import sys
import yaml
from pathlib import Path

CONFIG = Path(__file__).parent.parent / "config.yaml"

VALID_MODES = {"local", "cloud", "keyword-only"}
MODEL_KEYS = {"score": "score_model", "tailor": "tailor_model", "apply": "apply_model"}


def load() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def save(cfg: dict):
    CONFIG.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False))


def status(cfg: dict):
    mode = cfg.get("inference", {}).get("mode", "local")
    local = cfg.get("inference", {}).get("local", {})
    print(f"\n  Hermes Inference Mode: [{mode}]")
    print(f"  score  model : {local.get('score_model', '—')}")
    print(f"  tailor model : {local.get('tailor_model', '—')}")
    print(f"  apply  model : {local.get('apply_model', '—')}")
    cloud = cfg.get("inference", {}).get("cloud", {})
    print(f"  cloud  model : {cloud.get('apply_model', '—')} (used when mode=cloud)")
    print()


def switch_mode(cfg: dict, mode: str):
    if mode not in VALID_MODES:
        print(f"  ERROR: unknown mode '{mode}'. Valid: {', '.join(VALID_MODES)}")
        sys.exit(1)
    cfg.setdefault("inference", {})["mode"] = mode
    # Sync legacy keys so nothing breaks
    if mode == "local":
        local = cfg.get("inference", {}).get("local", {})
        cfg.setdefault("ollama", {})["model"] = local.get("score_model", "qwen3:4b")
        cfg.setdefault("ollama", {})["apply_model"] = local.get("apply_model", "qwen2.5:3b")
        cfg.setdefault("qwen", {})["model"] = local.get("score_model", "qwen3:4b")
    save(cfg)
    print(f"  ✓ Switched to mode: {mode}")


def switch_model(cfg: dict, stage: str, model: str):
    key = MODEL_KEYS.get(stage)
    if not key:
        print(f"  ERROR: unknown stage '{stage}'. Valid: {', '.join(MODEL_KEYS)}")
        sys.exit(1)
    cfg.setdefault("inference", {}).setdefault("local", {})[key] = model
    # Sync legacy keys
    if stage in ("score", "tailor"):
        cfg.setdefault("ollama", {})["model"] = model
        cfg.setdefault("qwen", {})["model"] = model
    elif stage == "apply":
        cfg.setdefault("ollama", {})["apply_model"] = model
    save(cfg)
    print(f"  ✓ {stage} model → {model}")


def main():
    args = sys.argv[1:]
    if not args:
        cfg = load()
        status(cfg)
        print("  Usage: python scripts/switch_mode.py <mode|model|status>")
        return

    cfg = load()

    if args[0] == "status":
        status(cfg)
    elif args[0] == "model":
        if len(args) < 3:
            print("  Usage: python scripts/switch_mode.py model <score|tailor|apply> <model-name>")
            sys.exit(1)
        switch_model(cfg, args[1], args[2])
        status(cfg)
    elif args[0] in VALID_MODES:
        switch_mode(cfg, args[0])
        status(cfg)
    else:
        print(f"  Unknown command: {args[0]}")
        print("  Usage: python scripts/switch_mode.py <local|cloud|keyword-only|model|status>")
        sys.exit(1)


if __name__ == "__main__":
    main()
