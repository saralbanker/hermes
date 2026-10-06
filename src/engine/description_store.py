"""Durable description text storage.

DATA_MODEL.md §6.2's `source_observations` schema deliberately has no raw
description column — only `description_hash`/`description_ref` — per §22
Evidence Record: "Keep evidence compact and durable. Do not store full HTML
by default." That leaves the actual text needing somewhere durable to live
so evaluation.py (embedding/scoring) and engine_apply.py (tailoring) can
read it back after discovery; `description_ref` is exactly the field the
schema provides for that pointer. This module is the one place that reads/
writes what it points to — a bounded per-opportunity text file, not a
second, uncoordinated copy of the DB's evidence-compactness rule.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DESCRIPTIONS_DIR = ROOT / "output" / "descriptions"
MAX_CHARS = 8000  # bounded — this is a ranking/tailoring input, not an archive


def write(opportunity_id: int, text: str) -> str | None:
    """Writes (overwrites) this opportunity's current description text.
    Returns the relative ref to store in `source_observations.description_ref`,
    or None if there is nothing to store."""
    if not text:
        return None
    DESCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    rel_path = f"output/descriptions/{opportunity_id}.txt"
    (ROOT / rel_path).write_text(text[:MAX_CHARS], encoding="utf-8")
    return rel_path


def read(description_ref: str | None) -> str:
    if not description_ref:
        return ""
    path = ROOT / description_ref
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
