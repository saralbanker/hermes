"""src/tailor.py — PROOF_BY_VARIANT's load-time guard (plan §2.4).

template_letter() never goes through facts()/candidate_text(), so PROOF_BY_VARIANT's
hardcoded proof paragraphs are not covered by project_registry.redact_retired_sections —
the module itself raises RuntimeError at import time if any paragraph names a retired
project (static code constant, no "typo in prose" risk class, safe to hard-fail at import).

This test re-executes the real module source (not a hand-copied reimplementation of the
guard) with one proof paragraph tampered to include a retired project name, proving the
guard actually fires on the exact code in the file — not just on logic the test
reimplements separately.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TAILOR_PATH = ROOT / "src" / "tailor.py"
TAILOR_SOURCE = TAILOR_PATH.read_text(encoding="utf-8")


def test_real_tailor_module_is_currently_clean():
    """Sanity check: the real, currently-committed file must not itself be tripping the
    guard (if it did, nothing importing tailor.py would work at all)."""
    import tailor  # already imported cleanly by every other test module; re-assert here
    for variant, text in tailor.PROOF_BY_VARIANT.items():
        for name in tailor.RETIRED_PROJECTS:
            assert name.lower() not in text.lower(), f"PROOF_BY_VARIANT[{variant!r}] names {name!r}"


@pytest.mark.parametrize("retired_name", ["Shade Ledger", "HeatMax", "Carbon Compass"])
def test_load_time_guard_raises_when_a_proof_paragraph_names_a_retired_project(retired_name):
    assert retired_name not in TAILOR_SOURCE  # sanity: the real file is clean of this name
    tampered = TAILOR_SOURCE.replace(
        '"backend": ("I built AWIS,',
        f'"backend": ("I built {retired_name}, formerly AWIS,',
        1,
    )
    assert tampered != TAILOR_SOURCE, "the targeted literal must actually exist to tamper with"

    namespace = {"__name__": "tailor_tampered_for_test", "__file__": str(TAILOR_PATH)}
    with pytest.raises(RuntimeError, match=retired_name):
        exec(compile(tampered, str(TAILOR_PATH), "exec"), namespace)
