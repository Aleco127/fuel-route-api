"""Shared test fixtures: synthetic routes and stations (no network)."""
from __future__ import annotations

import pytest

from apps.fuel.models import FuelStation


def straight_route(lat_start: float, lat_end: float, lng: float = -100.0):
    """A north-south route along one meridian (~69 mi per degree lat).

    Returns ordered (lat, lng) points, fine enough for checkpoint sampling.
    """
    steps = int(abs(lat_end - lat_start) / 0.1) + 1
    sign = 1 if lat_end >= lat_start else -1
    return [(round(lat_start + sign * 0.1 * i, 4), lng) for i in range(steps)]


@pytest.fixture
def make_station(db):
    def _make(lat, lng, price, name="S", state="TX"):
        return FuelStation.objects.create(
            name=name,
            state=state,
            latitude=lat,
            longitude=lng,
            price_per_gallon=price,
        )

    return _make
