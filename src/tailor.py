"""
tailor.py — For each status='scored' job above threshold, write a truthful,
targeted cover letter, save it to output/tailored/, update DB.

Honesty guarantees (the owner's hard requirement):
  • The LLM sees only profile/facts.md and writes just two paragraphs
    (why this role, one relevant proof). The closing paragraph is fixed text.
  • validate_letter() rejects any number not present in the fact sheet, any
    percentage, and any claim of a skill/domain the fact sheet lists as absent.
  • Two failed attempts → deterministic template built from facts only.

CLI:
  python src/tailor.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, get_jobs_above_score, update_job
from keywords import extract_keywords, missing_keywords
from llm import LLMUnavailable, chat, facts

ROOT = Path(__file__).parent.parent


def load_config() -> dict:
    return yaml.safe_load(open(ROOT / "config.yaml"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def select_resume_variant(title: str, description: str) -> str:
    """
    Choose which resume variant to attach. Title decides first (it is the
    strongest signal); description keywords only break ties.
    Returns 'ai' | 'backend' | 'fullstack'.
    """
    ai_re = re.compile(r"\b(ai|llm|ml|machine learning|rag|nlp|genai|gen ai|artificial intelligence)\b", re.I)
    backend_re = re.compile(r"\b(backend|back-end|api|platform|infrastructure|golang|go developer|python developer)\b", re.I)
    fullstack_re = re.compile(r"\b(full[- ]?stack|frontend|front-end|react|next\.?js)\b", re.I)
    for text in (title, (description or "")[:1500]):
        if ai_re.search(text):
            return "ai"
        if fullstack_re.search(text):
            return "fullstack"
        if backend_re.search(text):
            return "backend"
    return "fullstack"


def make_slug(company: str, title: str) -> str:
    """Generate a filesystem-safe slug from company + title."""
    raw = f"{company}-{title}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw)[:60].strip("-")


# ---------------------------------------------------------------------------
# Cover letter generation
# ---------------------------------------------------------------------------

CLOSING = (
    "I build with AI coding agents such as Claude Code as a deliberate part of my workflow: "
    "I write the specification and acceptance criteria, own the architecture, and review and "
    "test every change myself. I'm based in Ahmedabad, available immediately, and comfortable "
    "working remotely across time zones.\n\n"
    "Saral Banker | saralbanker1@gmail.com | +91 9016990136 | github.com/saralbanker"
)

# Proof paragraphs for the fallback template — every claim is taken from facts.md.
PROOF_BY_VARIANT = {
    "ai": ("I built Neuro-Zenith, a local-first AI productivity platform with a RAG pipeline "
           "(BGE embeddings, pgvector HNSW semantic search), Redis and BullMQ background jobs, "
           "and multi-provider LLM routing across OpenRouter, Gemini and local Qwen models."),
    "backend": ("I built AWIS, an event-sourced workflow engine in Go: a YAML workflow DSL with "
                "retries and compensation, an append-only SQLite event log rebuilt by replay, and "
                "773 Go test functions gated by CI with the race detector."),
    "fullstack": ("As a freelancer I delivered Shade Ledger, a paid billing and collection system "
                  "for an industrial estate of 220+ units, built with React, TypeScript and "
                  "PostgreSQL. It replaced the client's Excel workflow and saves 40+ hours of "
                  "manual work each month."),
}

BANNED_CLAIM_RE = re.compile(
    r"\b(i have|i've|my|experience (in|with)|background in|expertise in|worked (in|with|on))"
    r"[^.]{0,60}\b(aws|gcp|google cloud|azure|kubernetes|k8s|healthcare|fintech|banking|"
    r"java\b|spring|\.net|php|ios|swift|team lead|led a team|managed a team|bachelor|degree in)", re.I)
HYPE_RE = re.compile(r"%|\bprecisely\b|\bexactly matches\b|\bperfect(ly)? (fit|match)", re.I)
NUMBER_RE = re.compile(r"\d[\d,.]*")


def _norm_number(raw: str) -> str:
    return raw.replace(",", "").rstrip(".")


@lru_cache(maxsize=1)
def allowed_numbers() -> frozenset[str]:
    """Every number in the fact sheet, plus its 'k' form (70,000 → '70' for '70k')."""
    nums = set()
    for raw in NUMBER_RE.findall(facts()):
        n = _norm_number(raw)
        nums.add(n)
        if n.isdigit() and int(n) >= 1000 and int(n) % 1000 == 0:
            nums.add(str(int(n) // 1000))
    return frozenset(nums)


def validate_letter(text: str) -> list[str]:
    """Return a list of problems; an empty list means the letter is safe to send."""
    problems = [f"number '{raw}' is not in the fact sheet"
                for raw in NUMBER_RE.findall(text) if _norm_number(raw) not in allowed_numbers()]
    claim = BANNED_CLAIM_RE.search(text)
    if claim:
        problems.append(f"claims a skill/domain the candidate lacks: '{claim.group(0)}'")
    if HYPE_RE.search(text):
        problems.append("contains a percentage or exaggerated fit claim")
    if len(text.split()) > 170:
        problems.append("longer than 170 words")
    return problems


def _llm_body(job: dict, focus_kws: list[str], feedback: str) -> str:
    system = (
        "You write the first two paragraphs of a cover letter for the candidate, first person.\n"
        "STRICT RULES: use ONLY facts from the FACT SHEET. Do not invent experience, employers, "
        "domains, metrics, or percentages. Do not claim a skill unless it is in the fact sheet. "
        "If the job needs something the candidate lacks, do not mention it.\n"
        "Paragraph 1 (2 sentences): what specifically about this role or company fits the "
        "candidate's real work. Paragraph 2 (2-3 sentences): the single most relevant project "
        "from the fact sheet, with its real numbers. No greeting, no sign-off, no lists. "
        "Max 120 words total."
    )
    prompt = (
        f"FACT SHEET:\n{facts()}\n\nJOB:\nCompany: {job['company']}\nTitle: {job['title']}\n"
        f"Relevant keywords: {', '.join(focus_kws[:8])}\n"
        f"Description: {(job['description'] or '')[:1500]}\n{feedback}"
    )
    return chat(prompt, system=system, temperature=0.4, max_tokens=260).strip()


def template_letter(job: dict, variant: str) -> str:
    opener = (f"I'm applying for the {job['title']} role at {job['company']}. "
              "I like owning systems end to end, from data model to deployment, and this role "
              "looks like that kind of work.")
    return f"{opener}\n\n{PROOF_BY_VARIANT[variant]}\n\n{CLOSING}"


def generate_cover_letter(job: dict, focus_kws: list[str], variant: str) -> tuple[str, str]:
    """Returns (letter, source) where source is 'llm' or 'template'."""
    feedback = ""
    for _ in range(2):
        try:
            body = _llm_body(job, focus_kws, feedback)
        except LLMUnavailable as exc:
            print(f"[tailor] LLM unavailable ({exc}) — using fact-only template")
            break
        problems = validate_letter(body)
        if not problems:
            return f"{body}\n\n{CLOSING}", "llm"
        feedback = "\nYOUR PREVIOUS DRAFT WAS REJECTED: " + "; ".join(problems) + ". Fix it."
    return template_letter(job, variant), "template"


# ---------------------------------------------------------------------------
# Per-job processor
# ---------------------------------------------------------------------------

def process_job(job: dict, dry_run: bool = False) -> dict:
    """Select variant, write a validated cover letter, save it, update DB."""
    url, title, company = job["url"], job["title"] or "", job["company"] or ""
    description = job["description"] or ""
    base = {"url": url, "title": title, "company": company}
    try:
        variant = select_resume_variant(title, description)
        focus_kws = missing_keywords(facts(), extract_keywords(description, top_n=20))
        letter, source = generate_cover_letter(job, focus_kws, variant)
        slug = make_slug(company, title)
        rel_path = f"output/tailored/{slug}-cover.txt"

        if dry_run:
            return {**base, "variant": variant, "source": source, "status": "dry_run",
                    "preview": letter[:300].replace("\n", " "), "error": None}

        abs_path = ROOT / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(letter, encoding="utf-8")
        update_job(url, {"resume_variant": variant, "cover_letter_path": rel_path, "status": "tailored"})
        return {**base, "variant": variant, "source": source, "status": "tailored",
                "cover_letter_path": rel_path, "error": None}
    except Exception as exc:  # record per-job failure; never abort the whole batch
        if not dry_run:
            update_job(url, {"status": "error", "status_reason": f"tailor_error: {exc}"})
        return {**base, "status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def _report(i: int, total: int, result: dict) -> str:
    status = result["status"]
    head = f"[tailor] ({i}/{total})"
    who = f"{result['company']} — {result['title']}"
    if status == "tailored":
        return f"{head} OK  [{result['variant']}/{result['source']}] {who}"
    if status == "dry_run":
        return f"{head} DRY [{result['variant']}/{result['source']}] {who}\n         {result['preview'][:160]}..."
    return f"{head} ERR {who}: {result['error']}"


def main(limit: int | None = None, dry_run: bool = False) -> None:
    init_db()
    cfg = load_config()
    min_score = cfg["search"]["min_score"]
    jobs = [dict(j) for j in get_jobs_above_score(min_score)]
    if limit:
        jobs = jobs[:limit]
    if not jobs:
        print(f"[tailor] No jobs with status='scored' and score>={min_score}.")
        return

    print(f"[tailor] {len(jobs)} jobs qualify (score >= {min_score})."
          f"{' DRY RUN — no files written.' if dry_run else ''}")
    counts: dict[str, int] = {}
    # Sequential — Ollama on CPU is single-stream; parallel calls only cause timeouts.
    for i, job in enumerate(jobs, 1):
        result = process_job(job, dry_run)
        key = f"{result['status']}/{result.get('source', '-')}"
        counts[key] = counts.get(key, 0) + 1
        print(_report(i, len(jobs), result), flush=True)
    print(f"\n[tailor] Done. {counts}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate truthful cover letters for scored jobs")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to tailor")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Preview without writing files or updating DB")
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run)
