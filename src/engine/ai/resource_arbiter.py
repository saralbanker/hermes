"""Resource-aware scheduling + Ollama/browser RSS arbitration.

Implements SYSTEM_RULES.md §24's rule (added in Phase 2, DATA_MODEL-adjacent
patch, cited verbatim below) for real:

    "Before loading or reloading a generative/scoring model, check current
    browser process RSS (BROWSER_SYSTEM.md §81); before opening a new browser
    context mid-cycle, check current Ollama RSS. If combined measured RSS
    would exceed the safe ceiling established during IMPLEMENTATION_ROADMAP.md
    §22's resource baseline, the lower-priority operation defers per the
    existing priority order (AI_SYSTEM.md §74)."

AI_SYSTEM.md §74 Active Browser Priority: an active browser attempt always
wins over a background AI batch. §82 Resource Exhaustion: stop new heavy
inference, release/unload, record pressure, recover.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

import psutil

from . import gateway

# AI_SYSTEM.md §70: "16 GB RAM ... practical AI RAM budget of about 7-10 GB".
# This implementation's chosen ceiling, inside that frozen range — see the
# Phase 4 report for the measured numbers that justify 9 GB specifically
# (idle system + browser + AI, measured on this host: Ryzen 7 7730U, 16 GB
# RAM, Vega 8 iGPU sharing system RAM, CPU-only inference).
JOINT_RSS_CEILING_BYTES = 9 * 1024 ** 3


class Priority(str, Enum):
    ACTIVE_BROWSER = "ACTIVE_BROWSER"      # §74: always wins
    BACKGROUND_AI = "BACKGROUND_AI"


@dataclass(frozen=True)
class ArbitrationDecision:
    proceed: bool
    reason: str
    browser_rss_bytes: int
    ollama_rss_bytes: int
    combined_bytes: int
    ceiling_bytes: int


def measure_ollama_rss_bytes() -> int:
    """Sum of RSS across all `ollama runner`/`ollama_llama_server` child
    processes actually holding a model in memory right now (AI_SYSTEM.md
    §101: 'RSS where measurable' — this is the measurable operational
    metric, not model package size, per §71 Runtime Memory)."""
    total = 0
    for proc in psutil.process_iter(["name", "cmdline", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmdline = " ".join(proc.info["cmdline"] or []).lower()
            if "ollama" in name or "ollama" in cmdline or "llama-server" in cmdline:
                total += proc.info["memory_info"].rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def measure_browser_rss_bytes(browser_pids: list[int] | None = None) -> int:
    """BROWSER_SYSTEM.md §81 rss_bytes telemetry. Without explicit PIDs
    (the normal case — the browser worker reports its own PIDs; this
    function also works standalone for measurement/testing), sums every
    chromium/chrome process found, which over-counts an unrelated running
    browser on a dev machine — callers that own a specific browser session
    should pass its PIDs explicitly."""
    if browser_pids is not None:
        total = 0
        for pid in browser_pids:
            try:
                total += psutil.Process(pid).memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return total
    total = 0
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            if "chrome" in name or "chromium" in name:
                total += proc.info["memory_info"].rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def arbitrate_model_load(
    *, priority: Priority = Priority.BACKGROUND_AI,
    browser_pids: list[int] | None = None,
    ceiling_bytes: int = JOINT_RSS_CEILING_BYTES,
) -> ArbitrationDecision:
    """Call before loading/reloading a generative or scoring model.

    §74 Active Browser Priority is absolute: an ACTIVE_BROWSER-priority
    caller (an attempt's own decision-support AI call) always proceeds —
    deferring it would itself violate §74 ("serve active attempt before
    starting a large background scoring batch"). Only BACKGROUND_AI-priority
    calls (bulk scoring/embedding batches) are gated on the joint ceiling.
    """
    browser_rss = measure_browser_rss_bytes(browser_pids)
    ollama_rss = measure_ollama_rss_bytes()
    combined = browser_rss + ollama_rss

    if priority is Priority.ACTIVE_BROWSER:
        return ArbitrationDecision(True, "active browser attempt — always proceeds (§74)",
                                    browser_rss, ollama_rss, combined, ceiling_bytes)
    if combined > ceiling_bytes:
        return ArbitrationDecision(
            False, f"combined RSS {combined / 1024**3:.2f} GB exceeds ceiling "
                   f"{ceiling_bytes / 1024**3:.2f} GB — deferring background AI work",
            browser_rss, ollama_rss, combined, ceiling_bytes,
        )
    return ArbitrationDecision(True, "within joint RSS ceiling", browser_rss, ollama_rss,
                                combined, ceiling_bytes)


def arbitrate_browser_open(
    *, ceiling_bytes: int = JOINT_RSS_CEILING_BYTES,
) -> ArbitrationDecision:
    """Call before opening a new browser context mid-cycle (the other half
    of §24's rule: checking Ollama RSS before browser work, not just
    browser RSS before model loads)."""
    browser_rss = measure_browser_rss_bytes()
    ollama_rss = measure_ollama_rss_bytes()
    combined = browser_rss + ollama_rss
    if combined > ceiling_bytes:
        return ArbitrationDecision(
            False, f"combined RSS {combined / 1024**3:.2f} GB exceeds ceiling "
                   f"{ceiling_bytes / 1024**3:.2f} GB — release/unload an idle AI role before "
                   f"opening a new browser context (§82 Resource Exhaustion)",
            browser_rss, ollama_rss, combined, ceiling_bytes,
        )
    return ArbitrationDecision(True, "within joint RSS ceiling", browser_rss, ollama_rss,
                                combined, ceiling_bytes)


def release_pressure(role: str) -> None:
    """§82 Resource Exhaustion: stop new heavy inference, release/unload
    model, record resource pressure, recover. Unloading is best-effort
    (gateway.unload already swallows connection errors)."""
    gateway.unload(role)
