"""Pure geometry helpers (no Django / no network) - trivially unit-testable."""
from __future__ import annotations

import math

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points, in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def cumulative_distances(coords: list[tuple[float, float]]) -> list[float]:
    """Cumulative along-path distance (miles) for ordered (lat, lng) points.

    Index ``i`` holds the distance from the start of the path to ``coords[i]``.
    """
    cum = [0.0]
    for i in range(1, len(coords)):
        lat1, lng1 = coords[i - 1]
        lat2, lng2 = coords[i]
        cum.append(cum[-1] + haversine_miles(lat1, lng1, lat2, lng2))
    return cum


def degrees_per_mile_lat() -> float:
    """~1 degree of latitude is a constant number of miles everywhere."""
    return 1.0 / 69.0


def lng_degrees_for_miles(miles: float, at_latitude: float) -> float:
    """Longitude degrees that span ``miles`` at the given latitude.

    Used to build a bounding box that shrinks toward the poles.
    """
    miles_per_deg_lng = 69.172 * math.cos(math.radians(at_latitude))
    miles_per_deg_lng = max(miles_per_deg_lng, 1e-6)
    return miles / miles_per_deg_lng
