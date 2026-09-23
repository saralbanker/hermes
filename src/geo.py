"""
geo.py — Decide whether a job's location is workable for the candidate.

Eligible when either:
  • remote AND open to someone living in India (not "US only", "EU only", …), or
  • on-site/hybrid within cfg.geo.radius_km of home (Shahibaug, Ahmedabad).

Offline gazetteer — no geocoding API, no rate limits, deterministic.

    is_location_eligible(location, title, description, cfg) -> (bool, reason)
"""
from __future__ import annotations

import math
import re

# (lat, lon) of places a posting might name near Ahmedabad. Distances from
# Shahibaug decide eligibility, so Gandhinagar/GIFT City pass at 20 km while
# Sanand (≈23 km), Kalol, Mehsana, Vadodara, Rajkot, Surat do not.
GAZETTEER: dict[str, tuple[float, float]] = {
    "shahibaug": (23.0555, 72.5936),
    "ahmedabad": (23.0225, 72.5714),
    "sg highway": (23.0300, 72.5070),
    "s.g. highway": (23.0300, 72.5070),
    "prahlad nagar": (23.0120, 72.5108),
    "bodakdev": (23.0395, 72.5064),
    "thaltej": (23.0500, 72.5000),
    "satellite": (23.0300, 72.5170),
    "vastrapur": (23.0370, 72.5290),
    "navrangpura": (23.0365, 72.5611),
    "maninagar": (22.9962, 72.6030),
    "chandkheda": (23.1090, 72.5850),
    "motera": (23.0990, 72.5950),
    "science city": (23.0750, 72.4960),
    "bopal": (23.0330, 72.4640),
    "gota": (23.1030, 72.5410),
    "gift city": (23.1600, 72.6840),
    "gandhinagar": (23.2156, 72.6369),
    "infocity": (23.1930, 72.6340),
    "sanand": (22.9920, 72.3810),
    "kalol": (23.2460, 72.4960),
    "mehsana": (23.5880, 72.3693),
    "vadodara": (22.3072, 73.1812),
    "baroda": (22.3072, 73.1812),
    "surat": (21.1702, 72.8311),
    "rajkot": (22.3039, 70.8022),
}

REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed|telecommute)\b", re.I)
OPEN_TO_INDIA_RE = re.compile(
    r"\b(india|apac|asia|worldwide|world ?wide|anywhere|global(ly)?|any location|all countries|"
    r"ist\b|utc\s*\+\s*5)", re.I)
# Regions/countries that, when named as the only remote scope, exclude India.
RESTRICTED_RE = re.compile(
    r"\b(us|usa|u\.s\.a?|united states|canada|uk|u\.k\.|united kingdom|europe|eu|emea|latam|"
    r"latin america|brazil|mexico|germany|france|spain|poland|portugal|netherlands|ireland|"
    r"australia|new zealand|singapore|philippines|japan|americas|north america|"
    r"[a-z]+,\s*(ca|ny|tx|wa|ma|co|il|ga|fl|or|va|nc|nj|pa|az|ut|mn))\b", re.I)
RESIDENCY_RE = re.compile(
    r"(must|should|need to) (be )?(located|based|reside|live)[^.]{0,40}\b"
    r"(us|usa|united states|canada|uk|europe|eu|latam|americas)\b|"
    r"(us|u\.s\.|united states)[- ]based (candidates|applicants) only|"
    r"authori[sz]ed to work in the (us|united states|uk|eu)", re.I)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _local_match(location: str, home: tuple[float, float], radius: float) -> tuple[bool, str] | None:
    """Return a verdict if the location names a gazetteer place, else None."""
    loc = location.lower()
    hits = [(name, haversine_km(home, xy)) for name, xy in GAZETTEER.items() if name in loc]
    if not hits:
        return None
    # A posting naming a specific area overrides the generic city ("SG Highway, Ahmedabad").
    specific = [h for h in hits if h[0] != "ahmedabad"] or hits
    name, dist = min(specific, key=lambda h: h[1])
    if dist <= radius:
        return True, f"local:{name} {dist:.0f}km"
    return False, f"too_far:{name} {dist:.0f}km"


def _remote_verdict(location: str, description: str) -> tuple[bool, str]:
    loc = location.lower()
    if OPEN_TO_INDIA_RE.search(loc) or re.search(r"(^|,)\s*in\s*$", loc):
        return True, "remote:open_to_india"
    if RESTRICTED_RE.search(loc):
        return False, f"remote_restricted:{location[:40]}"
    if RESIDENCY_RE.search(description[:4000]):
        return False, "remote_residency_required"
    return True, "remote:unrestricted"


def is_location_eligible(location: str | None, title: str | None,
                         description: str | None, cfg: dict) -> tuple[bool, str]:
    geo = cfg["geo"]
    home = (geo["home_lat"], geo["home_lon"])
    location, title, description = location or "", title or "", description or ""

    is_remote = bool(REMOTE_RE.search(location) or REMOTE_RE.search(title))
    if is_remote:
        return _remote_verdict(location, description)

    local = _local_match(location, home, geo["radius_km"])
    if local is not None:
        return local
    if not location.strip():
        # Unknown location: accept only if the description itself says remote/Ahmedabad.
        if REMOTE_RE.search(description[:3000]):
            return _remote_verdict("", description)
        local = _local_match(description[:3000], home, geo["radius_km"])
        return local if local else (False, "location_unknown")
    return False, f"onsite:{location[:40]}"
