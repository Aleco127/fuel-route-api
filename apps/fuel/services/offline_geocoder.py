"""
Offline (city, state) -> (lat, lng) resolver.

The assessment's fuel file has NO coordinates, so every station must be
placed on the map. Doing that with an online geocoder means thousands of
network calls (slow, rate-limited, fragile). Instead we resolve coordinates
from the ``zipcodes`` package, which bundles the full US ZIP database
(~42k entries) locally:

  * zero network calls -> import runs in seconds, works on any machine
  * deterministic and reproducible
  * city-level accuracy (~98% of the file's US cities resolve)

A city's coordinate is the mean of its ZIP-code points (a stable centroid).
Non-US rows (Canadian provinces) have no entry and are left for the caller
to skip - consistent with the USA-only requirement.
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _city_index() -> dict[tuple[str, str], tuple[float, float]]:
    """Build {(CITY, ST): (lat, lng)} once from the offline ZIP dataset."""
    import zipcodes

    acc: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for rec in zipcodes.list_all():
        city = (rec.get("city") or "").strip().upper()
        state = (rec.get("state") or "").strip().upper()
        lat, lng = rec.get("lat"), rec.get("long")
        if not city or not state or lat in (None, "") or lng in (None, ""):
            continue
        try:
            point = (float(lat), float(lng))
        except (TypeError, ValueError):
            continue
        acc.setdefault((city, state), []).append(point)

    index: dict[tuple[str, str], tuple[float, float]] = {}
    for key, pts in acc.items():
        index[key] = (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )
    return index


def geocode_city_state(city: str, state: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a US (city, state), or None if not found."""
    if not city or not state:
        return None
    idx = _city_index()
    c, s = city.strip().upper(), state.strip().upper()
    if (c, s) in idx:
        return idx[(c, s)]
    # Tolerate spacing variants, e.g. "DE FOREST" vs "DEFOREST".
    c2 = c.replace(" ", "")
    for (ic, is_), pt in idx.items():
        if is_ == s and ic.replace(" ", "") == c2:
            return pt
    return None
