"""
Geocoding via Nominatim (OpenStreetMap) - NO API KEY required.

Geocoding is only invoked when the caller passes a *text* location. When
lat/lng are supplied this module is never touched, which keeps external
calls at zero for the coordinate path.

Two cache layers keep Nominatim calls minimal and respect its usage policy:
  1. process cache (Django LocMem) - instant repeat hits within a run
  2. GeocodeCache table             - survives restarts and is shared with
                                      the `import_fuel_prices --geocode` job
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_CACHE_TTL = 60 * 60 * 24  # 24h process cache


class GeocodingError(Exception):
    """Raised when a text location cannot be resolved to coordinates."""


def _cache_key(query: str) -> str:
    import hashlib

    digest = hashlib.md5(query.strip().lower().encode()).hexdigest()
    return f"geocode:{digest}"


def _try_offline_city_state(query: str) -> tuple[float, float, str] | None:
    """Resolve a "City, ST[, USA]" string from the offline ZIP dataset.

    Returns (lat, lng, display) or None if the input is not a recognisable
    city/state pair. No network. This is what makes the demo work offline.
    """
    from apps.fuel.services.offline_geocoder import geocode_city_state
    from apps.fuel.services.us_centroids import STATE_CENTROIDS

    parts = [p.strip() for p in query.split(",") if p.strip()]
    if parts and parts[-1].upper() in {"USA", "US", "UNITED STATES"}:
        parts = parts[:-1]
    if len(parts) < 2:
        return None
    state = parts[-1].upper()
    city = parts[-2]
    if state not in STATE_CENTROIDS:
        return None
    point = geocode_city_state(city, state)
    if point is None:
        return None
    return point[0], point[1], f"{city.title()}, {state}, USA (offline)"


def geocode_text(query: str) -> tuple[float, float, str]:
    """Resolve free-text -> (lat, lng, display_name), USA-biased and cached.

    Raises :class:`GeocodingError` on no match or provider failure.
    """
    query = query.strip()
    if not query:
        raise GeocodingError("Empty location string.")

    key = _cache_key(query)
    cached = cache.get(key)
    if cached:
        return cached

    # Avoid importing models at module load (keeps geo helpers light).
    from apps.fuel.models import GeocodeCache

    row = GeocodeCache.objects.filter(query__iexact=query).first()
    if row:
        result = (row.latitude, row.longitude, row.display_name)
        cache.set(key, result, _CACHE_TTL)
        return result

    # Fast offline path: "City, ST" (the common demo input) is resolved from
    # the bundled ZIP dataset with ZERO network calls. This keeps the API
    # fully usable without internet and instant for typical inputs.
    offline = _try_offline_city_state(query)
    if offline is not None:
        lat, lng, display = offline
        GeocodeCache.objects.get_or_create(
            query=query,
            defaults={"latitude": lat, "longitude": lng, "display_name": display},
        )
        cache.set(key, (lat, lng, display), _CACHE_TTL)
        return (lat, lng, display)

    url = f"{settings.NOMINATIM_BASE_URL.rstrip('/')}/search"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",  # bias/restrict to the USA per the brief
        "addressdetails": 0,
    }
    headers = {"User-Agent": settings.GEOCODER_USER_AGENT}
    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=settings.GEOCODING_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Geocoding failed for %r: %s", query, exc)
        raise GeocodingError(f"Geocoding provider error for '{query}'.") from exc

    if not data:
        raise GeocodingError(f"Could not geocode '{query}' within the USA.")

    item = data[0]
    lat, lng = float(item["lat"]), float(item["lon"])
    display = item.get("display_name", "")

    GeocodeCache.objects.get_or_create(
        query=query,
        defaults={"latitude": lat, "longitude": lng, "display_name": display},
    )
    result = (lat, lng, display)
    cache.set(key, result, _CACHE_TTL)
    return result
