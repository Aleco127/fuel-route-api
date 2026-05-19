"""
Greedy fuel-stop optimizer.

The brief explicitly allows a practical, explainable greedy heuristic rather
than a provably optimal one. The algorithm, end to end:

  1. Take the single route geometry already fetched by the routing service.
  2. Compute cumulative distance along the polyline.
  3. Sample the route into checkpoints every ``CHECKPOINT_SPACING_MILES``.
  4. ONE DB query: pull stations inside the route's bounding box (expanded by
     the search radius). This is the key performance decision - we never
     compare every station against every route point.
  5. For each station, snap it to its nearest checkpoint; keep it only if it
     is within ``STATION_SEARCH_RADIUS_MILES`` of the route. Its
     ``distance_from_start`` is that checkpoint's cumulative distance
     (a documented approximation - good to ~the checkpoint spacing).
  6. Greedy walk: from the current mile, look ahead one tank (``max_range``);
     among reachable candidates pick the cheapest (preferring legs >=
     ``MIN_LEG_MILES`` so stops don't cluster), jump to it, repeat until the
     destination is within range.
  7. Fuel accounting: total fuel for the trip is exactly
     ``distance / mpg``; the optimizer only decides WHERE it is bought. Each
     stop buys enough to reach the next stop / destination.

Fuel assumption (documented): the vehicle departs with an EMPTY tank, so a
station must exist within ``max_range`` of the start; the start->first-stop
fuel is bought at the first stop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

from apps.fuel.models import FuelStation

from .geo_utils import (
    cumulative_distances,
    haversine_miles,
    lng_degrees_for_miles,
)

logger = logging.getLogger(__name__)


# Route is sampled this finely for station snapping. It must be well below
# STATION_SEARCH_RADIUS_MILES so a station sitting *on* the route is never
# dropped just because the nearest sample point is far (the bug a coarse
# checkpoint spacing would cause). Bounded count keeps it fast.
SNAP_STEP_MILES = 3.0


@dataclass
class Checkpoint:
    cumulative_miles: float
    lat: float
    lng: float


@dataclass
class Candidate:
    station: FuelStation
    distance_from_start_miles: float
    offset_from_route_miles: float


@dataclass
class FuelPlanResult:
    stops: list[dict] = field(default_factory=list)
    total_fuel_cost: float | None = None
    notes: list[str] = field(default_factory=list)
    feasible: bool = True


def _sample_route(
    coords: list[tuple[float, float]], step_miles: float
) -> list[Checkpoint]:
    """Resample the route to ~``step_miles`` spacing (plus first & last).

    Used for station snapping. A small step keeps offset measurement
    accurate; the bounded sample count (route_len / step) keeps the
    snap loop fast and avoids an O(stations x raw_vertices) scan.
    """
    cum = cumulative_distances(coords)
    total = cum[-1]
    samples: list[Checkpoint] = []
    target = 0.0
    i = 0
    while target <= total:
        while i < len(cum) - 1 and cum[i] < target:
            i += 1
        lat, lng = coords[i]
        samples.append(Checkpoint(cum[i], lat, lng))
        target += step_miles
    last_lat, last_lng = coords[-1]
    if not samples or samples[-1].cumulative_miles < total - 1e-6:
        samples.append(Checkpoint(total, last_lat, last_lng))
    return samples


def _route_bounding_box(coords: list[tuple[float, float]], pad_miles: float):
    lats = [c[0] for c in coords]
    lngs = [c[1] for c in coords]
    mid_lat = (min(lats) + max(lats)) / 2
    lat_pad = pad_miles / 69.0
    lng_pad = lng_degrees_for_miles(pad_miles, mid_lat)
    return (
        min(lats) - lat_pad,
        max(lats) + lat_pad,
        min(lngs) - lng_pad,
        max(lngs) + lng_pad,
    )


def _gather_candidates(
    samples: list[Checkpoint], radius: float
) -> list[Candidate]:
    """Single bounding-box DB query, then snap stations to the route."""
    coords = [(cp.lat, cp.lng) for cp in samples]
    min_lat, max_lat, min_lng, max_lng = _route_bounding_box(coords, radius)

    # PERFORMANCE: one indexed query over the route corridor only.
    qs = FuelStation.objects.filter(
        latitude__gte=min_lat,
        latitude__lte=max_lat,
        longitude__gte=min_lng,
        longitude__lte=max_lng,
    ).only(
        "id", "name", "brand", "address", "city", "state",
        "latitude", "longitude", "price_per_gallon",
    )

    candidates: list[Candidate] = []
    for st in qs.iterator(chunk_size=2000):
        best_d = None
        best_cp = None
        # Compare only against the resampled route (~route_len/step points),
        # NOT against every raw route vertex.
        for cp in samples:
            d = haversine_miles(st.latitude, st.longitude, cp.lat, cp.lng)
            if best_d is None or d < best_d:
                best_d, best_cp = d, cp
        if best_d is not None and best_d <= radius:
            candidates.append(
                Candidate(
                    station=st,
                    distance_from_start_miles=round(best_cp.cumulative_miles, 2),
                    offset_from_route_miles=round(best_d, 2),
                )
            )
    candidates.sort(key=lambda c: c.distance_from_start_miles)
    return candidates


def _greedy_select(
    candidates: list[Candidate],
    total_distance: float,
    max_range: float,
    min_leg: float,
    notes: list[str],
) -> tuple[list[Candidate], bool]:
    """Pick the cheapest reachable station within each tank window."""
    # Short trip: the whole route fits in one tank -> buy all fuel once, at
    # the single cheapest reachable station.
    if total_distance <= max_range:
        reachable = [c for c in candidates if c.distance_from_start_miles <= total_distance]
        if not reachable:
            notes.append(
                "Route is within one tank but no station was found along it; "
                "fuel cost could not be computed."
            )
            return [], False
        cheapest = min(
            reachable,
            key=lambda c: (c.station.price_per_gallon, c.distance_from_start_miles),
        )
        return [cheapest], True

    selected: list[Candidate] = []
    position = 0.0
    feasible = True
    while total_distance - position > max_range:
        window = [
            c
            for c in candidates
            if position < c.distance_from_start_miles <= position + max_range
        ]
        if not window:
            notes.append(
                f"No fuel station found within {max_range:.0f} mi after mile "
                f"{position:.0f}; the route may not be completable with the "
                "available stations."
            )
            feasible = False
            break

        # Prefer stops that are not bunched together; relax if forced.
        spaced = [
            c for c in window if c.distance_from_start_miles - position >= min_leg
        ]
        pool = spaced or window
        chosen = min(
            pool,
            key=lambda c: (
                c.station.price_per_gallon,
                -c.distance_from_start_miles,  # tie-break: go as far as possible
            ),
        )
        selected.append(chosen)
        position = chosen.distance_from_start_miles

    return selected, feasible


def optimize_fuel_plan(
    route_coords: list[tuple[float, float]],
    total_distance_miles: float,
) -> FuelPlanResult:
    """Compute the cost-optimised fuel stops for a route.

    ``route_coords`` are ordered (lat, lng) points decoded from the routing
    provider's geometry. Returns a :class:`FuelPlanResult` with serialisable
    stop dicts, the total fuel cost and human-readable notes.
    """
    max_range = settings.VEHICLE_MAX_RANGE_MILES
    mpg = settings.VEHICLE_MPG
    radius = settings.STATION_SEARCH_RADIUS_MILES
    min_leg = settings.MIN_LEG_MILES
    # Snap resolution: fine enough that an on-route station is never lost,
    # capped so it never exceeds a third of the search radius.
    step = min(SNAP_STEP_MILES, max(radius / 3.0, 1.0))

    result = FuelPlanResult()
    samples = _sample_route(route_coords, step)
    candidates = _gather_candidates(samples, radius)

    if not candidates:
        result.feasible = total_distance_miles <= max_range
        result.notes.append(
            "No fuel stations were found near this route in the database. "
            "Import a fuel-price file covering this region."
        )
        return result

    selected, feasible = _greedy_select(
        candidates, total_distance_miles, max_range, min_leg, result.notes
    )
    result.feasible = feasible

    # Fuel accounting. Total fuel == distance / mpg; we partition the trip
    # so each stop pays for the distance until the next stop / destination.
    total_cost = 0.0
    prev_marker = 0.0
    for idx, cand in enumerate(selected):
        next_marker = (
            selected[idx + 1].distance_from_start_miles
            if idx + 1 < len(selected)
            else total_distance_miles
        )
        gallons = max(next_marker - prev_marker, 0.0) / mpg
        prev_marker = next_marker
        cost = gallons * cand.station.price_per_gallon
        total_cost += cost
        st = cand.station
        result.stops.append(
            {
                "stop_number": idx + 1,
                "station_name": st.name,
                "brand": st.brand,
                "address": st.address,
                "city": st.city,
                "state": st.state,
                "lat": round(st.latitude, 6),
                "lng": round(st.longitude, 6),
                "price_per_gallon": round(st.price_per_gallon, 4),
                "distance_from_start_miles": round(
                    cand.distance_from_start_miles, 2
                ),
                "offset_from_route_miles": cand.offset_from_route_miles,
                "gallons_purchased": round(gallons, 2),
                "estimated_cost": round(cost, 2),
            }
        )

    result.total_fuel_cost = round(total_cost, 2) if selected else None
    return result
