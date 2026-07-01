"""
tailor.py — For each status='scored' job above threshold, generate a
targeted cover letter via Qwen 2.5, save to output/tailored/, update DB.

Uses ThreadPoolExecutor(max_workers=3) for concurrency since Qwen calls
are synchronous HTTP requests (no asyncio needed).

CLI:
  python src/tailor.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, get_jobs_above_score, update_job, get_conn

sys.path.insert(0, str(Path(__file__).parent))
from keywords import extract_keywords, missing_keywords

# ---------------------------------------------------------------------------
# Saral's master resume text (same as score.py — keep in sync)
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
# Helpers
# ---------------------------------------------------------------------------

def select_resume_variant(title: str, description: str) -> str:
    """
    Choose which resume variant to attach based on role keywords.
    Returns 'ai' | 'backend' | 'fullstack'.
    """
    text = (title + " " + (description or "")).lower()
    ai_kws = [
        "ai", "llm", "ml", "machine learning", "rag", "nlp",
        "artificial intelligence", "embedding", "vector", "genai",
    ]
    backend_kws = [
        "backend", "api", "server", "database", "infrastructure",
        "platform", "devops", "cloud", "microservice",
    ]
    if any(kw in text for kw in ai_kws):
        return "ai"
    if any(kw in text for kw in backend_kws):
        return "backend"
    return "fullstack"


def make_slug(company: str, title: str) -> str:
    """Generate a filesystem-safe slug from company + title."""
    raw = f"{company}-{title}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw)[:60].strip("-")


# ---------------------------------------------------------------------------
# Qwen interface
# ---------------------------------------------------------------------------

def call_qwen(prompt: str, system: str = "", cfg: dict = None) -> str:
    """Call local Ollama model via /api/chat. Raises RuntimeError if Ollama is not reachable."""
    ollama_cfg = (cfg or {}).get("ollama", (cfg or {}).get("qwen", {})) or {
        "base_url": "http://localhost:11434",
        "model": "qwen3:4b",
        "timeout": 200,
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{ollama_cfg['base_url']}/api/chat",
            json={
                "model": ollama_cfg["model"],
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.5},
                "keep_alive": ollama_cfg.get("keep_alive", "15m"),
            },
            timeout=ollama_cfg.get("timeout", 300),
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Ollama not reachable at localhost:11434. Run: ollama serve")
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama timed out. Is ollama serve running with model loaded?")


COVER_LETTER_TEMPLATE = """I'm applying for the {title} role at {company} because it aligns directly with the systems I've been building — full-stack, production-grade, with real ownership from schema to deployment.

I independently architected and shipped Neuro-Zenith: a 70k+ LOC modular AI platform spanning a full RAG pipeline, Socket.IO real-time collaboration, BullMQ async job processing, multi-provider LLM routing, and a 4-pipeline GitHub Actions CI/CD system. I also delivered a production financial operations platform as a paid contract for a 220-unit rental business — replacing manual Excel billing with automated PDF invoicing, WhatsApp delivery, and late-fee enforcement. My stack: TypeScript, React 18, Next.js, Node.js, FastAPI, PostgreSQL, Redis, Docker.

I'm available immediately and prefer remote. Happy to discuss further.

— Saral Banker | saralbanker1@gmail.com | github.com/saralbanker"""


def generate_cover_letter(job: dict, missing_kws: list[str], cfg: dict) -> str:
    """Generate a targeted cover letter via Qwen; fall back to template if Qwen unavailable."""
    company = job["company"] or ""
    title = job["title"] or ""
    description = (job["description"] or "")[:1500]

    # Try Qwen first
    try:
        system = (
            "You are writing a targeted cover letter for Saral Banker, a Full Stack and AI Engineer.\n"
            "Write in first person. Professional but direct. No filler phrases. No 'Dear Hiring Manager'.\n"
            "Start with a strong hook sentence about THIS specific company/role.\n"
            "Maximum 200 words. Three short paragraphs only. Plain text, no lists, no headers."
        )
        prompt = f"""Write a cover letter for this role:

Company: {company}
Title: {title}
Key skills to naturally include: {", ".join(missing_kws[:8])}

Job Description (excerpt):
{description}

Candidate background:
- Neuro-Zenith: 70k+ LOC AI platform (RAG, Socket.IO, BullMQ, multi-provider LLM, CI/CD) — solo
- Shade Ledger: financial ops platform for 220-unit rental business, saved 40+ hrs/month — paid contract
- Stack: TypeScript, React 18, Next.js, Node.js, FastAPI, PostgreSQL, pgvector, Redis, Docker
- Available immediately, remote preferred

Paragraphs:
1. Hook — why THIS company/role specifically
2. Proof — one achievement from Neuro-Zenith or Shade Ledger most relevant here
3. Close — one sentence, available immediately"""
        return call_qwen(prompt, system=system, cfg=cfg)
    except RuntimeError:
        # Qwen unavailable — use the hardcoded template
        return COVER_LETTER_TEMPLATE.format(title=title, company=company)


# ---------------------------------------------------------------------------
# Per-job processor
# ---------------------------------------------------------------------------

def process_job(job: dict, cfg: dict, dry_run: bool = False) -> dict:
    """
    Process a single job: select variant, extract keywords, generate cover
    letter, save file, update DB.

    Returns a result dict with keys: url, title, company, status, error.
    """
    url = job["url"]
    title = job["title"] or ""
    company = job["company"] or ""
    description = job["description"] or ""

    try:
        # 1. Select resume variant
        variant = select_resume_variant(title, description)

        # 2. Extract JD keywords and find what's missing from resume
        jd_keywords = extract_keywords(description, top_n=20)
        missing_kws = missing_keywords(RESUME_TEXT, jd_keywords)

        # 3. Generate cover letter
        cover_letter = generate_cover_letter(job, missing_kws, cfg)

        # 4. Build output path
        slug = make_slug(company, title)
        rel_path = f"output/tailored/{slug}-cover.txt"
        abs_path = Path(__file__).parent.parent / rel_path

        if dry_run:
            preview = cover_letter[:300].replace("\n", " ")
            return {
                "url": url,
                "title": title,
                "company": company,
                "variant": variant,
                "slug": slug,
                "missing_kws": missing_kws[:5],
                "preview": preview,
                "status": "dry_run",
                "error": None,
            }

        # 5. Save cover letter to disk
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(cover_letter, encoding="utf-8")

        # 6. Update DB
        update_job(url, {
            "resume_variant": variant,
            "cover_letter_path": rel_path,
            "status": "tailored",
        })

        return {
            "url": url,
            "title": title,
            "company": company,
            "variant": variant,
            "slug": slug,
            "missing_kws": missing_kws[:5],
            "cover_letter_path": rel_path,
            "status": "tailored",
            "error": None,
        }

    except Exception as exc:
        error_msg = str(exc)
        if not dry_run:
            update_job(url, {"status": "error", "status_reason": f"tailor_error: {error_msg}"})
        return {
            "url": url,
            "title": title,
            "company": company,
            "status": "error",
            "error": error_msg,
        }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main(limit: int | None = None, dry_run: bool = False) -> None:
    init_db()
    cfg = load_config()
    min_score = cfg.get("search", {}).get("min_score", 7.5)

    jobs = get_jobs_above_score(min_score)
    if limit:
        jobs = jobs[:limit]

    total = len(jobs)
    if total == 0:
        print(f"[tailor] No jobs with status='scored' and score>={min_score}. Run score.py first.")
        return

    print(
        f"[tailor] {total} jobs qualify (score >= {min_score}).  "
        f"{'DRY RUN — no files written.' if dry_run else 'Generating cover letters...'}"
    )

    results = {"tailored": 0, "error": 0, "dry_run": 0}

    # Sequential — Ollama is single-threaded on CPU; concurrent calls just cause timeouts
    for i, job in enumerate(jobs, 1):
        try:
            result = process_job(job, cfg, dry_run)
        except Exception as exc:
            print(f"[tailor] ({i}/{total}) Unexpected error: {exc}")
            results["error"] += 1
            continue

        status = result.get("status", "error")
        title = result.get("title", "?")
        company = result.get("company", "?")

        if status == "tailored":
            results["tailored"] += 1
            variant = result.get("variant", "?")
            path = result.get("cover_letter_path", "?")
            print(f"[tailor] ({i}/{total}) OK  [{variant}] {company} — {title}  →  {path}")
        elif status == "dry_run":
            results["dry_run"] += 1
            variant = result.get("variant", "?")
            slug = result.get("slug", "?")
            missing = result.get("missing_kws", [])
            preview = result.get("preview", "")
            print(
                f"[tailor] ({i}/{total}) DRY  [{variant}] {company} — {title}\n"
                f"         slug: {slug}\n"
                f"         missing kws: {missing}\n"
                f"         preview: {preview[:120]}...\n"
            )
        else:
            results["error"] += 1
            error = result.get("error", "unknown")
            print(f"[tailor] ({i}/{total}) ERR  {company} — {title}: {error}")

    print(
        f"\n[tailor] Done.  "
        f"Tailored: {results['tailored']}  "
        f"Dry-run previews: {results['dry_run']}  "
        f"Errors: {results['error']}"
    )
    if not dry_run and results["tailored"] > 0:
        out_dir = Path(__file__).parent.parent / "output" / "tailored"
        print(f"[tailor] Cover letters saved to: {out_dir}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate cover letters for scored jobs")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to tailor")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview what would be generated without writing files or updating DB",
    )
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run)
