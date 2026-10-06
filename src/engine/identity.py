"""Canonical identity — DATA_MODEL.md §5.3.

    The canonical identity hierarchy is:
        1. reliable source-specific job ID
        2. reliable ATS/company posting ID
        3. normalized composite identity

    The fallback composite must include enough discriminating information to
    avoid obvious false merges. At minimum: normalized company + normalized
    title + normalized location + relevant employment/posting discriminator.
    Company + title alone is not sufficient as the universal canonical key.

None of the sources this phase ingests (python-jobspy/Indeed, Greenhouse/
Lever/Ashby, WWR, Arbeitnow, Himalayas, Remotive, RemoteOK) expose a
field this codebase currently normalizes into a cross-source-comparable
"reliable source-specific job ID" (tiers 1-2), so `canonical_key()` below
uses the explicit §5.3 tier-3 fallback — company + title + location +
employment type — which is what lets the SAME role listed on two different
boards (different URLs) resolve to ONE opportunity (DATA_MODEL §5.4: "source
URLs may change without creating a new opportunity").

This is deliberately NOT the formula scripts/migrate_phase1.py used
(company + title + URL): that one-time historical migration had the
opposite goal — guarantee no false merge among already-distinct legacy
`jobs` rows, each with its own already-unique URL — and that script is
frozen, already run against the live DB, and not touched here.
"""

from __future__ import annotations


def normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def canonical_key(
    company: str | None, title: str | None, location: str | None = None,
    employment_type: str | None = None,
) -> str:
    return (
        f"{normalize(company)}::{normalize(title)}::"
        f"{normalize(location)}::{normalize(employment_type)}"
    )
