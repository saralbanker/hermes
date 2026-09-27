"""Offline tests for src/geo.py — no network, no Ollama."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from geo import is_location_eligible


def load_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    return yaml.safe_load(open(cfg_path))


CFG = load_config()


def test_remote_open_to_india():
    ok, reason = is_location_eligible("Remote, India", "Software Engineer", "", CFG)
    assert ok
    assert "remote" in reason


def test_remote_us_only_excludes_india():
    ok, reason = is_location_eligible("Remote (US only)", "Software Engineer", "", CFG)
    assert not ok


def test_remote_eu_only_excludes_india():
    ok, reason = is_location_eligible("Remote, EU", "Backend Engineer", "", CFG)
    assert not ok


def test_remote_worldwide_ok():
    ok, reason = is_location_eligible("Remote, Worldwide", "Full Stack Engineer", "", CFG)
    assert ok


def test_onsite_gandhinagar_within_20km():
    ok, reason = is_location_eligible("Gandhinagar, Gujarat", "Software Engineer", "", CFG)
    assert ok
    assert "local" in reason


def test_onsite_sanand_beyond_20km():
    ok, reason = is_location_eligible("Sanand, Gujarat", "Software Engineer", "", CFG)
    assert not ok
    assert "too_far" in reason


def test_night_shift_onsite_beyond_10km_rejected():
    # Infocity, Gandhinagar is ~15.8km from Shahibaug — within the day radius
    # (20km) but beyond the night-shift radius (10km).
    ok, reason = is_location_eligible(
        "Infocity, Gandhinagar", "Software Engineer",
        "This role requires working night shift (9pm-6am IST) to overlap with the US team.",
        CFG,
    )
    assert not ok
    assert "too_far" in reason


def test_night_shift_onsite_within_10km_accepted():
    # Satellite, Ahmedabad is ~8.3km from Shahibaug — within the night radius (10km).
    ok, reason = is_location_eligible(
        "Satellite, Ahmedabad", "Software Engineer",
        "Candidates must be willing to work a graveyard shift.",
        CFG,
    )
    assert ok
    assert "local" in reason


def test_remote_night_shift_is_fine():
    ok, reason = is_location_eligible(
        "Remote, India", "Software Engineer",
        "This is a US shift / night shift role, fully remote.",
        CFG,
    )
    assert ok


def test_us_canada_remote_scopes_rejected():
    """Regression: Webflow 'CA Remote (BC & ON only); U.S. Remote' passed on 2026-09-23."""
    from geo import is_location_eligible
    cfg = {"geo": {"home_lat": 23.0555, "home_lon": 72.5936, "radius_km": 20, "night_radius_km": 10}}
    for loc in ["CA Remote (BC & ON only); U.S. Remote", "U.S. Remote", "Remote - U.K.", "Remote (US)"]:
        assert not is_location_eligible(loc, "Engineer", "", cfg)[0], loc
    desc = "Location: Remote-first (United States; BC & ON Canada)\nFull-time"
    assert not is_location_eligible("Remote", "Engineer", desc, cfg)[0]
    assert is_location_eligible("Remote", "Engineer", "Location: Remote (India)", cfg)[0]
