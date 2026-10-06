"""project_registry.py — the ONE place that says whether a tracked project is active or
retired, which numbers belong to it (tailor.py's misattribution check), and how to redact
retired content from raw fact-sheet text. Dependency-free by design: both src/llm.py and
src/engine/ai/embed.py read profile/facts.md independently (the engine module is
deliberately isolated from llm.py) and must derive the SAME redaction from this one
module — no other file may define a second retired-name list or redaction routine."""
from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass(frozen=True)
class ProjectInfo:
    status: str                  # "active" | "retired"
    numbers: frozenset[str]

PROJECTS: dict[str, ProjectInfo] = {
    "AWIS":           ProjectInfo("active",  frozenset({"25000","25","773","31000","31","168","22","12"})),
    "Neuro-Zenith":   ProjectInfo("active",  frozenset({"70000","70","44","400"})),
    "Hermes":         ProjectInfo("active",  frozenset()),
    "Shade Ledger":   ProjectInfo("retired", frozenset({"60000","60","220","40"})),
    "HeatMax":        ProjectInfo("retired", frozenset()),
    "Carbon Compass": ProjectInfo("retired", frozenset()),
}
RETIRED_PROJECTS: frozenset[str] = frozenset(n for n, p in PROJECTS.items() if p.status == "retired")

class FactsRedactionError(RuntimeError):
    """Raised when facts.md's RETIRED delimiters don't match project_registry.RETIRED_PROJECTS
    — redaction cannot be guaranteed safe, so NO LLM prompt may be built from facts.md
    until this is fixed. This is a fail-CLOSED signal for the current generation request
    only: both call sites (tailor.py's process_job, engine_apply.py's _tailor) already
    wrap generation in a per-job try/except that marks just that job failed/retryable and
    continues the batch — verified at src/tailor.py:246 and src/engine_apply.py:152. A
    drift is NOT silently worked around with a partial name-only scrub: substantive
    retired-project evidence (numbers, descriptions) could still leak through prose that
    never contains the literal project name, which a name-only substitution would miss."""

_RETIRED_BLOCK_RE = re.compile(r"<!--\s*RETIRED:([^>]*?)\s*-->.*?<!--\s*/RETIRED\s*-->\n?", re.S)

def redact_retired_sections(raw: str) -> str:
    """Strip RETIRED-delimited blocks from `raw`. Fails CLOSED (raises FactsRedactionError)
    if the delimited names don't exactly match RETIRED_PROJECTS — never falls back to a
    weaker, partial redaction. See FactsRedactionError's docstring for why this is safe at
    the call-site level (per-job failure, not a pipeline-wide crash)."""
    delimited = {m.group(1).strip() for m in re.finditer(r"<!--\s*RETIRED:([^>]*?)\s*-->", raw)}
    if delimited != set(RETIRED_PROJECTS):
        raise FactsRedactionError(
            f"facts.md RETIRED delimiters {delimited} != project_registry.RETIRED_PROJECTS "
            f"{set(RETIRED_PROJECTS)} — refusing to build any LLM prompt from facts.md until fixed"
        )
    return _RETIRED_BLOCK_RE.sub("", raw)
