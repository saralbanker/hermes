"""Age-band recomputation — DATA_MODEL.md §27.1 "Recomputation Contract".

`opportunities.age_band` is a denormalized cache. The canonical value is
always `f(age_basis, age_reference_at, now)`, recomputed live at claim time
(never read from the stale cached column for a claim decision) and persisted
by a periodic sweep. This module is the single `f`.
"""

from __future__ import annotations

import datetime as dt

from .policy import AGE_BAND_HOUR_BOUNDARIES
from .enums import AGE_BAND_EXPIRED


def _parse(ts: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def compute_age_band(age_reference_at: str | None, now: str | None = None) -> str:
    """Live, canonical age-band computation.

    ARCHITECTURE_REDESIGN_FINAL...FROZEN.md §3.2: 0-72h / >72-168h /
    >168-336h / >336-504h / >504h = EXPIRED.
    """
    if not age_reference_at:
        return AGE_BAND_EXPIRED
    try:
        ref = _parse(age_reference_at)
    except ValueError:
        return AGE_BAND_EXPIRED
    now_dt = _parse(now) if now else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    age_hours = (now_dt - ref).total_seconds() / 3600.0
    for band, upper_bound_hours in AGE_BAND_HOUR_BOUNDARIES:
        if age_hours <= upper_bound_hours:
            return band
    return AGE_BAND_EXPIRED


def is_within_horizon(age_reference_at: str | None, now: str | None = None) -> bool:
    return compute_age_band(age_reference_at, now) != AGE_BAND_EXPIRED
