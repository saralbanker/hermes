"""
score.py — Score status='discovered' jobs against the candidate's verified facts.

Pipeline:
  1. Load 'discovered' jobs (already location/seniority/salary filtered by discover.py).
  2. Embedding pre-rank (nomic-embed-text): cosine(job, fact sheet). Jobs below
     min_similarity are marked filtered; the rest are LLM-scored best-first, capped
     at max_llm_per_run so a backlog never blocks the apply stage.
  3. LLM score 1–10 with the fact sheet as a fixed prompt prefix — Ollama reuses the
     cached prefix, so each job costs only its own tokens (~10 s on CPU vs ~33 s).
  4. If the LLM is unavailable, keyword scoring keeps the pipeline moving.

CLI:
  python src/score.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, get_jobs_by_status, update_job
from filters import role_priority
from llm import LLMUnavailable, chat, cosine, embed, facts, is_ready

SCORE_SYSTEM = (
    "You are a strict technical recruiter. Rate how likely this candidate gets an interview "
    "for the job, 1-10, using ONLY the fact sheet. 9-10: stack and seniority match closely. "
    "6-8: most required skills match, experience requirement is 0-3 years. "
    "1-5: needs skills, degree, or years the candidate lacks. "
    'Output JSON only: {"score": <int 1-10>, "reason": "<max 15 words>"}'
)


def load_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    return yaml.safe_load(open(cfg_path))


def _parse_score_response(response: str) -> tuple[float, str]:
    """Parse the model's JSON; regex fallback for slightly malformed output."""
    cleaned = re.sub(r"```(?:json)?", "", response).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
        return float(data["score"]), str(data.get("reason", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    score_match = re.search(r'"score"\s*:\s*([0-9]+(?:\.[0-9]+)?)', response)
    if score_match:
        reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', response)
        return float(score_match.group(1)), reason_match.group(1) if reason_match else "regex fallback"
    raise ValueError(f"Could not parse scoring response: {response[:200]}")


def score_job(job: dict) -> tuple[float, str]:
    """LLM score 1–10. Fact sheet first so the prompt prefix is cache-reused."""
    prompt = (
        f"FACT SHEET:\n{facts()}\n\n"
        f"JOB:\nCompany: {job['company']}\nTitle: {job['title']}\n"
        f"Location: {job['location']}\nDescription: {(job['description'] or '')[:1800]}"
    )
    response = chat(prompt, system=SCORE_SYSTEM, temperature=0.1, json_mode=True, max_tokens=60)
    score, reason = _parse_score_response(response)
    return max(1.0, min(10.0, score)), reason


def job_text(job: dict) -> str:
    return f"{job['title']}. {(job['description'] or '')[:2000]}"


def rank_by_similarity(jobs: list, batch: int = 16) -> list[tuple[float, dict]]:
    """Cosine similarity of each job to the fact sheet, highest first."""
    profile_vec = embed(["search_query: " + facts()[:6000]])[0]
    ranked = []
    for i in range(0, len(jobs), batch):
        chunk = jobs[i:i + batch]
        vecs = embed(["search_document: " + job_text(j) for j in chunk])
        ranked += [(cosine(profile_vec, v), j) for v, j in zip(vecs, chunk)]
    return sorted(ranked, key=lambda x: x[0], reverse=True)


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


def _score_one(job: dict, use_llm: bool) -> tuple[float, str, bool]:
    """Returns (score, reason, llm_still_available)."""
    if use_llm:
        try:
            score, reason = score_job(job)
            return score, reason, True
        except LLMUnavailable as e:
            print(f"[score] LLM dropped mid-run ({e}) — switching to keyword fallback.")
    score, reason = keyword_score_fallback(job)
    return score, reason, False


def _prerank(jobs: list, cfg: dict, use_llm: bool) -> list:
    """Drop low-similarity jobs; return the rest ordered (role_priority, similarity)
    best-first, capped per run — AI/LLM and backend roles get scored before the LLM
    budget runs out on lower-priority ones."""
    scfg = cfg.get("scoring", {})
    if not use_llm:
        return jobs[: scfg.get("max_llm_per_run", 250)]
    ranked = rank_by_similarity(jobs)
    floor = scfg.get("min_similarity", 0.0)
    keep = []
    for sim, job in ranked:
        if sim < floor:
            update_job(job["url"], {"status": "filtered", "status_reason": f"low_similarity:{sim:.2f}"})
        else:
            keep.append((sim, job))
    print(f"[score] Embedding pre-rank: {len(keep)} above similarity {floor}, "
          f"{len(ranked) - len(keep)} filtered")
    keep.sort(key=lambda sj: (role_priority(sj[1].get("title") or "",
                                            sj[1].get("description") or ""), sj[0]),
              reverse=True)
    return [job for _sim, job in keep][: scfg.get("max_llm_per_run", 250)]


def main(limit: int | None = None) -> None:
    init_db()
    cfg = load_config()
    use_llm = is_ready()
    print(f"[score] LLM {'ready — AI scoring' if use_llm else 'unavailable — keyword fallback'}.")

    jobs = [dict(j) for j in get_jobs_by_status("discovered")]
    if limit:
        jobs = jobs[:limit]
    if not jobs:
        print("[score] Nothing to score. Run discover.py first.")
        return
    print(f"[score] {len(jobs)} jobs to score.")

    try:
        queue = _prerank(jobs, cfg, use_llm)
    except LLMUnavailable as e:
        print(f"[score] Embedding pre-rank failed ({e}) — scoring in DB order.")
        queue = jobs[: cfg.get("scoring", {}).get("max_llm_per_run", 250)]

    scored, total = [], len(queue)
    for i, job in enumerate(queue, 1):
        try:
            score, reason, use_llm = _score_one(job, use_llm)
        except ValueError as exc:  # unparseable model output — record, don't crash
            update_job(job["url"], {"status": "error", "status_reason": f"scoring_error: {exc}"})
            print(f"[score] ({i}/{total}) ERROR '{job['title']}': {exc}")
            continue
        update_job(job["url"], {"score": score, "score_reason": reason, "status": "scored"})
        scored.append(score)
        print(f"[score] ({i}/{total}) {job['company']} — {job['title']} → {score:.1f} | {reason[:60]}")

    avg = round(sum(scored) / len(scored), 2) if scored else 0.0
    print(f"\n[score] Done — scored: {len(scored)}, avg: {avg} "
          f"(apply threshold ≥{cfg['search']['min_score']})")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score discovered jobs with the local LLM")
    parser.add_argument("--limit", type=int, default=None, help="Max jobs to process")
    args = parser.parse_args()
    main(limit=args.limit)
