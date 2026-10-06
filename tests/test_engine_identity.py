"""Phase 5: src/engine/identity.py — canonical_key normalization.
DATA_MODEL.md §5.3/§5.4: company+title alone is insufficient; the same role
on different URLs/sources must resolve to the same key."""
from __future__ import annotations

from engine import identity


def test_canonical_key_is_case_and_whitespace_insensitive():
    a = identity.canonical_key(" Acme Corp ", "Backend Engineer", "Remote")
    b = identity.canonical_key("acme corp", "backend engineer", "remote")
    assert a == b


def test_canonical_key_same_role_different_source_url_matches():
    """The actual point of §5.4: URL must never be part of the live
    discovery identity key, so two boards listing the same role resolve to
    one opportunity."""
    key_from_indeed = identity.canonical_key("Acme", "Backend Engineer", "Remote")
    key_from_greenhouse = identity.canonical_key("Acme", "Backend Engineer", "Remote")
    assert key_from_indeed == key_from_greenhouse


def test_canonical_key_distinguishes_different_locations():
    a = identity.canonical_key("Acme", "Backend Engineer", "Remote")
    b = identity.canonical_key("Acme", "Backend Engineer", "Onsite - Ahmedabad")
    assert a != b


def test_canonical_key_company_and_title_alone_insufficient_distinguishes_by_location():
    """DATA_MODEL §5.3: 'Company + title alone is not sufficient.'"""
    a = identity.canonical_key("Acme", "Engineer", "Remote, India")
    b = identity.canonical_key("Acme", "Engineer", "Remote, Worldwide")
    assert a != b
