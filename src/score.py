"""
score.py — Score status='discovered' jobs against Saral's resume.

Pipeline:
  1. Load all 'discovered' jobs from DB.
  2. Pre-filter with TF-IDF cosine similarity (keyword_overlap_score).
     Jobs below min_overlap are marked error='below_overlap_threshold'.
  3. Remaining jobs are scored by Qwen 2.5 Instruct.
  4. DB is updated with score, score_reason, status='scored'.

CLI:
  python src/score.py [--limit N] [--min-overlap 0.20]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, get_jobs_by_status, update_job

sys.path.insert(0, str(Path(__file__).parent))
from keywords import keyword_overlap_score

# ---------------------------------------------------------------------------
# Saral's master resume text (used verbatim in Qwen scoring prompts)
# ---------------------------------------------------------------------------

RESUME_TEXT = """
CANDIDATE: Saral Banker — Full Stack Engineer · AI Application Developer · Founding Engineer

SKILLS:
Languages: TypeScript, JavaScript, Python, SQL, Java, Kotlin
Frontend: React 18, Next.js, Vite, Tailwind CSS, shadcn/ui, Framer Motion, TanStack Query, Zustand
Backend: Node.js, Express 4, FastAPI, REST API Design, Socket.IO 4, SSE
AI & LLMs: RAG Pipelines, pgvector HNSW, BGE-base-576M embeddings, OpenRouter API, Gemini API,
           local Qwen 2.5 Instruct, prompt engineering, structured output parsing, multi-provider LLM routing,
           AI model evaluation (GPT-4, Claude, Gemini, DeepSeek, Qwen, Kimi, Gemma, MiniMax)
Databases: PostgreSQL (raw pg driver, 44 migrations), Supabase, Redis 7, MySQL, SQLite, pgvector
Infrastructure: Docker, Docker Compose, GitHub Actions CI/CD (4 pipelines), GHCR, Terraform, Supabase CLI
Architecture: Modular Monolith + Microservice, BullMQ async jobs, event-driven Redis pub/sub,
              Multi-tenant RBAC, JWT auth, rate limiting, audit logging, PRD writing
Observability: Sentry, Prometheus, Pino structured logging
Mobile: Kotlin, XML, SQLite (Android)

EXPERIENCE:
- Contract Full Stack Engineer (Jan 2025–Mar 2026, 15 months):
  Built financial operations platform for 220-unit rental business from scratch.
  Automated billing, PDF invoices via WhatsApp Business API, late-fee penalty logic.
  Saved 40+ hours/month. Rs.60,000 paid contract. Stack: React, Next.js, TypeScript, Node.js, PostgreSQL, Supabase.

PROJECTS:
- Neuro-Zenith (2025–2026): 70k+ LOC, 400+ files, 44 DB migrations. Modular AI platform.
  Full RAG pipeline (ingestion → BGE embeddings → pgvector HNSW → semantic search).
  Socket.IO real-time collaboration (2 namespaces, Redis pub/sub).
  BullMQ/Redis async job processing + DB polling queue.
  Multi-provider LLM routing (OpenRouter, Gemini, local Qwen 2.5).
  3-layer RBAC (auth + workspace + project middleware).
  Prometheus + Sentry observability. 4-pipeline GitHub Actions CI/CD.
  Docker Compose. 30 backend test files (Jest 29 + Supertest). 6 frontend test files.
  Stack: React 18, Vite, TypeScript, Node.js 20, Express 4, FastAPI, Python 3.14,
         PostgreSQL, Supabase, Redis 7, BullMQ 5, pgvector, Socket.IO 4,
         OpenRouter, Gemini API, Qwen 2.5, BGE-base-576M, Docker, GitHub Actions, Terraform.

EDUCATION: Diploma in Computer Engineering, LJ Polytechnic (May 2026), CGPA 8.36/10, Top 10% of class.
CERTS: IBM Python for Data Science · Google Cybersecurity · Agile Project Management
""".strip()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    return yaml.safe_load(open(cfg_path))


# ---------------------------------------------------------------------------
# Qwen interface
# ---------------------------------------------------------------------------

def call_qwen(prompt: str, system: str = "", cfg: dict = None) -> str:
    """Call local Ollama model. Raises RuntimeError if Ollama is not reachable."""
    ollama_cfg = (cfg or {}).get("ollama", (cfg or {}).get("qwen", {})) or {
        "base_url": "http://localhost:11434",
        "model": "qwen3:4b",
        "timeout": 120,
    }
    try:
        resp = requests.post(
            f"{ollama_cfg['base_url']}/api/generate",
            json={
                "model": ollama_cfg["model"],
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 800, "think": False},
                "keep_alive": ollama_cfg.get("keep_alive", "10m"),
            },
            timeout=ollama_cfg.get("timeout", 120),
        )
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
        # Strip qwen3 thinking tokens if present
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return raw
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama not reachable at localhost:11434. Run: ollama serve")
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out. Is ollama serve running with model loaded?")


def check_qwen(cfg: dict) -> None:
    """Verify Ollama is reachable. Raises RuntimeError if not."""
    _ = call_qwen("Say 1", system="You are a test.", cfg=cfg)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _parse_score_response(response: str) -> tuple[float, str]:
    """
    Parse Qwen's JSON response into (score, reason).
    Falls back to regex extraction if full JSON parse fails.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", response).strip().rstrip("`").strip()

    # Attempt full parse first
    try:
        data = json.loads(cleaned)
        return float(data["score"]), str(data["reason"])
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Regex fallback: grab the first {...} block
    match = re.search(r"\{[^}]+\}", response, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return float(data["score"]), str(data.get("reason", ""))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Last resort: extract score number only
    score_match = re.search(r'"score"\s*:\s*([0-9]+(?:\.[0-9]+)?)', response)
    reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', response)
    if score_match:
        score = float(score_match.group(1))
        reason = reason_match.group(1) if reason_match else "parsed via regex fallback"
        return score, reason

    raise ValueError(f"Could not parse Qwen scoring response: {response[:200]}")


def score_job(job: dict, cfg: dict) -> tuple[float, str]:
    """
    Score a single job using Qwen 2.5.
    Returns (score: float 1.0–10.0, reason: str).
    """
    company = job["company"] or ""
    title = job["title"] or ""
    description = (job["description"] or "")[:1500]

    system = (
        "You are a technical recruiter scoring candidate-job fit.\n"
        'Respond ONLY with valid JSON: {"score": 8.5, "reason": "one sentence max 20 words"}\n'
        "No markdown, no explanation, JSON only."
    )

    prompt = f"""CANDIDATE RESUME:
{RESUME_TEXT}

JOB:
Company: {company}
Title: {title}
Description (first 1500 chars): {description}

Score fit 1.0-10.0. Weight these factors:
- TypeScript/Node.js/React/PostgreSQL match: highest weight
- Python/FastAPI/AI/RAG match: high weight
- Founding/startup/ownership fit: high weight
- Seniority: Saral has 2 years + Diploma. Penalise hard if role needs 5+ YOE or BSc required
- Remote-friendliness

JSON only."""

    response = call_qwen(prompt, system=system, cfg=cfg)
    return _parse_score_response(response)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

SARAL_CORE_SKILLS = [
    "typescript", "javascript", "python", "react", "next.js", "nextjs",
    "node.js", "nodejs", "node", "express", "fastapi", "postgresql", "postgres",
    "sql", "docker", "rest api", "api", "fullstack", "full stack", "full-stack",
    "backend", "frontend", "ai", "llm", "rag", "machine learning", "redis",
    "supabase", "socket.io", "github actions", "ci/cd", "terraform",
    "founding", "startup", "engineer", "developer", "software",
]


def keyword_score_fallback(job: dict) -> tuple[float, str]:
    """
    Score a job using keyword matching only — no LLM needed.
    Works on title alone if description is missing.
    Returns (score: float 1–10, reason: str).
    """
    text = ((job["title"] or "") + " " + (job["description"] or "")).lower()
    hits = [kw for kw in SARAL_CORE_SKILLS if kw in text]
    n = len(hits)
    if n >= 8:
        score = 8.5
    elif n >= 5:
        score = 7.5
    elif n >= 3:
        score = 6.0
    elif n >= 1:
        score = 4.5
    else:
        score = 2.0
    reason = f"keyword-match ({n} skill hits: {', '.join(hits[:5])})"
    return score, reason


def main(limit: int | None = None, min_overlap: float = 0.05) -> None:
    init_db()
    cfg = load_config()

    # Check Qwen — fall back to keyword scoring if unavailable
    qwen_available = False
    print("[score] Checking Qwen connectivity...")
    try:
        check_qwen(cfg)
        print("[score] Qwen reachable — using AI scoring.")
        qwen_available = True
    except RuntimeError as e:
        print(f"[score] Qwen unavailable ({e})")
        print("[score] Falling back to keyword-match scoring (no LLM needed).")

    jobs = get_jobs_by_status("discovered")
    if limit:
        jobs = jobs[:limit]

    total = len(jobs)
    print(f"[score] {total} jobs to score.")

    if total == 0:
        print("[score] Nothing to score. Run discover.py first.")
        return

    # Pre-filter: skip only jobs with very low overlap; no-description jobs score on title only
    qualifying = []
    skipped = 0
    for job in jobs:
        jd_text = job["description"] or ""
        title_text = job["title"] or ""
        if not jd_text.strip():
            # No description — can still keyword-score on title alone
            qualifying.append(job)
            continue
        overlap = keyword_overlap_score(RESUME_TEXT, jd_text)
        if overlap < min_overlap and not any(kw in title_text.lower() for kw in
                ["engineer", "developer", "typescript", "react", "node", "python", "ai", "full stack", "backend", "frontend"]):
            update_job(job["url"], {"status": "error", "status_reason": "below_overlap_threshold"})
            skipped += 1
        else:
            qualifying.append(job)

    print(f"[score] {skipped} skipped (very low overlap, irrelevant title). {len(qualifying)} qualifying.")

    scored_count = 0
    error_count = 0
    score_sum = 0.0

    for i, job in enumerate(qualifying, 1):
        url = job["url"]
        title = job["title"]
        company = job["company"]
        try:
            if qwen_available:
                score, reason = score_job(job, cfg)
            else:
                score, reason = keyword_score_fallback(job)
            update_job(url, {"score": score, "score_reason": reason, "status": "scored"})
            score_sum += score
            scored_count += 1
            print(f"[score] ({i}/{len(qualifying)}) {company} — {title} → {score:.1f} | {reason[:60]}")
        except RuntimeError as e:
            # Qwen went down mid-run — fall back for remaining jobs
            print(f"[score] Qwen dropped mid-run ({e}), switching to keyword fallback.")
            qwen_available = False
            score, reason = keyword_score_fallback(job)
            update_job(url, {"score": score, "score_reason": reason, "status": "scored"})
            score_sum += score
            scored_count += 1
        except Exception as exc:
            update_job(url, {"status": "error", "status_reason": f"scoring_error: {exc}"})
            error_count += 1
            print(f"[score] ({i}/{len(qualifying)}) ERROR '{title}': {exc}")

    avg = round(score_sum / scored_count, 2) if scored_count else 0.0
    cfg_min = cfg.get("search", {}).get("min_score", 7.5)
    print(f"\n[score] Done — scored: {scored_count}, errors: {error_count}, avg: {avg} (threshold ≥{cfg_min})")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score discovered jobs with Qwen 2.5")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to process")
    parser.add_argument(
        "--min-overlap",
        type=float,
        default=0.20,
        dest="min_overlap",
        help="TF-IDF cosine similarity threshold (default 0.20)",
    )
    args = parser.parse_args()
    main(limit=args.limit, min_overlap=args.min_overlap)
