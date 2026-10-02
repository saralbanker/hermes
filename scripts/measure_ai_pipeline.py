#!/usr/bin/env python3
"""Phase 4 measurement pass — real Ollama calls, real latency + RSS.

Per the Phase 4 brief: "the roadmap requires measured latency/RSS, not
estimates." This script is NOT part of the pytest suite (it requires real
Ollama and takes real wall-clock time) — it is run once, by hand, to produce
the numbers quoted in the Phase 4 report.

Usage:
    python3 scripts/measure_ai_pipeline.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine.ai import classify, embed, gateway, generate, rerank, resource_arbiter as ra

SAMPLE_JOB = {
    "company": "Acme Robotics",
    "title": "Backend Engineer",
    "description": (
        "We are looking for a Backend Engineer to build our core API platform using "
        "Python, FastAPI, and PostgreSQL. You will design REST APIs, work with Docker "
        "and CI/CD pipelines, and collaborate with the frontend team. 1-3 years of "
        "experience preferred."
    ),
}


def _measure(label: str, fn):
    rss_before = ra.measure_ollama_rss_bytes()
    t0 = time.monotonic()
    try:
        result = fn()
        ok = True
    except Exception as exc:  # measurement run: record the failure, don't crash the pass
        result = f"{type(exc).__name__}: {exc}"
        ok = False
    elapsed = time.monotonic() - t0
    rss_after = ra.measure_ollama_rss_bytes()
    status = "OK" if ok else "FAILED"
    print(f"\n=== {label}: {status} ===")
    print(f"  latency: {elapsed:.2f}s")
    print(f"  ollama RSS before: {rss_before / 1024**2:.0f} MB, after: {rss_after / 1024**2:.0f} MB "
          f"(delta: {(rss_after - rss_before) / 1024**2:+.0f} MB)")
    print(f"  result: {str(result)[:300]}")
    return {"label": label, "ok": ok, "latency_s": elapsed, "rss_before": rss_before,
            "rss_after": rss_after, "result": result}


def main() -> None:
    print("Phase 4 AI pipeline measurement pass — real Ollama calls on this host.")
    print(f"Role config: {gateway.load_role_config()}")

    results = []

    results.append(_measure(
        "embedding (nomic-embed-text)",
        lambda: embed.embed_batch(["search_document: " + SAMPLE_JOB["description"]])[0][0][:3],
    ))

    results.append(_measure(
        "reranking (dengcao/bge-reranker-v2-m3)",
        lambda: rerank.rerank("backend engineer python", [SAMPLE_JOB["description"], "unrelated marketing job"]),
    ))

    results.append(_measure(
        "scoring/classification (phi4-mini)",
        lambda: classify.score_job(SAMPLE_JOB["title"], SAMPLE_JOB["description"]),
    ))

    results.append(_measure(
        "generation/tailoring (qwen3.5:4b-q4_K_M)",
        lambda: generate.generate_cover_letter(SAMPLE_JOB, ["python", "fastapi", "postgresql"], "backend"),
    ))

    print("\n=== Summary ===")
    for r in results:
        print(f"  {r['label']:<45} {'OK ' if r['ok'] else 'FAIL'}  {r['latency_s']:6.2f}s")


if __name__ == "__main__":
    main()
