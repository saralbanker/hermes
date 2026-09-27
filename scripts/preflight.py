#!/usr/bin/env python3
"""
preflight.py — Readiness checks before a scheduled Hermes run.

Checks: network, Ollama (started on demand, waits for readiness), configured
models present (names come from config.yaml via llm.py — never duplicated here),
Xvfb display, Indeed session file, disk space.

Exit codes: 0 ready · 2 network down (run later) · 3 Ollama/model unavailable
(scoring/tailoring degrade, apply still runs) · 1 other hard failure.
Prints one line per check; run_hermes.sh decides what to do with the code.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from llm import installed_models, is_ready, llm_config, LLMUnavailable  # noqa: E402


def check_network(timeout: float = 5.0) -> bool:
    for host in ("www.indeed.com", "boards-api.greenhouse.io", "imap.gmail.com"):
        try:
            socket.create_connection((host, 443 if "imap" not in host else 993), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def _ollama_up() -> bool:
    try:
        requests.get(f"{llm_config()['base_url']}/api/tags", timeout=3).raise_for_status()
        return True
    except requests.RequestException:
        return False


def ensure_ollama(wait_seconds: int = 60) -> bool:
    """Start the user ollama.service (the instance that owns the models) if it is down."""
    if _ollama_up():
        return True
    subprocess.run(["systemctl", "--user", "start", "ollama.service"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    for _ in range(wait_seconds):
        time.sleep(1)
        if _ollama_up():
            return True
    return False


def main() -> int:
    code = 0
    net = check_network()
    print(f"[preflight] network: {'ok' if net else 'DOWN'}")
    if not net:
        return 2
    up = ensure_ollama()
    try:
        models = installed_models() if up else []
    except LLMUnavailable:
        models = []
    ready = up and is_ready()
    c = llm_config()
    print(f"[preflight] ollama: {'up' if up else 'DOWN'}; models ready: {ready} "
          f"(need {c['model']}, {c['embed_model']}; have {len(models)})")
    if not ready:
        code = 3
    xvfb = shutil.which("Xvfb") is not None
    print(f"[preflight] Xvfb: {'ok' if xvfb else 'MISSING (sudo pacman -S xorg-server-xvfb)'}")
    session = (ROOT / "output" / "indeed_session.json").exists()
    print(f"[preflight] indeed session file: {'present' if session else 'missing'}")
    free_gb = shutil.disk_usage(ROOT).free / 1e9
    print(f"[preflight] disk free: {free_gb:.1f} GB")
    if not xvfb or free_gb < 1:
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
