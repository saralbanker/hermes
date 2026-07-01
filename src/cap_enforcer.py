# src/cap_enforcer.py
"""Daily application cap enforcer. Call check_can_apply() before every submission."""

import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from db import count_today, get_daily_counts


class CapExceeded(Exception):
    """Raised when a daily limit is reached. Pipeline should stop or skip."""
    pass


def load_limits() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg["limits"]


def check_can_apply(job_board: str) -> None:
    """
    Call before every application attempt.
    job_board: 'linkedin' or any other string for non-LinkedIn boards.
    Raises CapExceeded if any daily limit is hit.
    Does nothing (returns None) if application is allowed.
    """
    limits = load_limits()

    total_today = count_today()
    if total_today >= limits["total_per_day"]:
        raise CapExceeded(
            f"Total daily cap reached: {total_today}/{limits['total_per_day']}. "
            "Pipeline stopping for today. Run again tomorrow."
        )

    if job_board == "linkedin":
        linkedin_today = count_today(board="linkedin")
        if linkedin_today >= limits["linkedin_per_day"]:
            raise CapExceeded(
                f"LinkedIn daily cap reached: {linkedin_today}/{limits['linkedin_per_day']}. "
                "Skipping LinkedIn for today, continuing with other boards."
            )


def remaining_today() -> dict:
    """Returns dict with remaining slots for each board type."""
    limits = load_limits()
    daily = get_daily_counts()
    linkedin_used = daily["linkedin_count"]
    other_used = daily["other_count"]
    total_used = daily["total_count"]
    return {
        "linkedin_remaining": max(0, limits["linkedin_per_day"] - linkedin_used),
        "other_remaining": max(0, limits["other_per_day"] - other_used),
        "total_remaining": max(0, limits["total_per_day"] - total_used),
        "linkedin_used": linkedin_used,
        "other_used": other_used,
        "total_used": total_used,
        "limits": limits,
    }


def print_status():
    """Print current daily limit status to stdout."""
    r = remaining_today()
    print(f"LinkedIn:  {r['linkedin_used']}/{r['limits']['linkedin_per_day']} used  "
          f"({r['linkedin_remaining']} remaining)")
    print(f"Other:     {r['other_used']}/{r['limits']['other_per_day']} used  "
          f"({r['other_remaining']} remaining)")
    print(f"Total:     {r['total_used']}/{r['limits']['total_per_day']} used  "
          f"({r['total_remaining']} remaining)")


if __name__ == "__main__":
    print_status()
