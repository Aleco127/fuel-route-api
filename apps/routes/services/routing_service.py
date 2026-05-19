"""
Routing via the public OSRM demo server - NO API KEY required.

Design goal from the brief: *minimise* external routing calls. We make
exactly **one** OSRM request per plan; that single call returns distance,
duration AND the full geometry, so nothing else is needed. Identical
requests are additionally memoised in the process cache.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_METERS_PER_MILE = 1609.344
_ROUTE_CACHE_TTL = 60 * 30  # 30 min


class RoutingError(Exception):
    """Raised when the routing provider fails or returns no route."""


@dataclass
class RouteResult:
    distance_miles: float
    duration_minutes: float
    # Ordered (lat, lng) points decoded from the route geometry.
    coordinates: list[tuple[float, float]]
    # GeoJSON LineString returned to the client (lng, lat order, per spec).
    geometry: dict
    provider: str = "OSRM"


def _cache_key(s_lat, s_lng, f_lat, f_lng) -> str:
    # Round to ~50 m so trivially-different coords reuse the same route.
    return f"route:{s_lat:.4f},{s_lng:.4f}:{f_lat:.4f},{f_lng:.4f}"


def get_route(
    start_lat: float,
    start_lng: float,
    finish_lat: float,
    finish_lng: float,
) -> RouteResult:
    """Fetch the driving route in a single OSRM call (geometry + distance)."""
    key = _cache_key(start_lat, start_lng, finish_lat, finish_lng)
    cached = cache.get(key)
    if cached:
        return cached

    # `overview=full` + `geometries=geojson` -> exact coordinates with no
    # extra polyline dependency, all in this one request.
    url = (
        f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/"
        f"{start_lng},{start_lat};{finish_lng},{finish_lat}"
    )
    params = {"overview": "full", "geometries": "geojson", "alternatives": "false"}
    try:
        resp = requests.get(
            url, params=params, timeout=settings.ROUTING_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Routing request failed: %s", exc)
        raise RoutingError("Routing provider is unavailable.") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError(
            "No drivable route found between the two locations."
        )

    route = data["routes"][0]
    geometry = route["geometry"]  # GeoJSON LineString: coords are [lng, lat]
    coords = [(lat, lng) for lng, lat in geometry["coordinates"]]
    if len(coords) < 2:
        raise RoutingError("Routing provider returned a degenerate geometry.")

    result = RouteResult(
        distance_miles=route["distance"] / _METERS_PER_MILE,
        duration_minutes=route["duration"] / 60.0,
        coordinates=coords,
        geometry=geometry,
        provider="OSRM",
    )
    cache.set(key, result, _ROUTE_CACHE_TTL)
    return result
