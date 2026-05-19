"""End-to-end API tests with the network boundary mocked out."""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from apps.routes.services.routing_service import RouteResult, RoutingError

from .conftest import straight_route

pytestmark = pytest.mark.django_db


def _fake_route():
    coords = straight_route(30.0, 40.0)  # ~690 mi
    from apps.routes.services.geo_utils import cumulative_distances

    total = cumulative_distances(coords)[-1]
    return RouteResult(
        distance_miles=total,
        duration_minutes=total,  # arbitrary
        coordinates=coords,
        geometry={"type": "LineString", "coordinates": [[c[1], c[0]] for c in coords]},
        provider="OSRM",
    )


@patch("apps.routes.views.get_route")
def test_route_fuel_plan_with_coordinates(mock_route, make_station):
    mock_route.return_value = _fake_route()
    make_station(34.0, -100.0, price=3.10, name="Cheap Stop")
    make_station(38.0, -100.0, price=3.40, name="Second Stop")

    client = APIClient()
    resp = client.post(
        "/api/route-fuel-plan/",
        {
            "start": {"lat": 30.0, "lng": -100.0},
            "finish": {"lat": 40.0, "lng": -100.0},
        },
        format="json",
    )

    assert resp.status_code == 200, resp.content
    body = resp.json()
    for key in ("start", "finish", "route", "vehicle", "fuel_plan",
                "total_fuel_cost", "notes"):
        assert key in body
    assert body["route"]["map_provider"] == "OSRM"
    assert body["vehicle"]["max_range_miles"] == 500
    assert len(body["fuel_plan"]) >= 1
    # Coordinate input must NOT trigger geocoding (asserted by no patch needed).


@patch("apps.routes.views.geocode_text")
@patch("apps.routes.views.get_route")
def test_route_fuel_plan_with_text_locations(mock_route, mock_geo, make_station):
    mock_route.return_value = _fake_route()
    mock_geo.side_effect = [
        (30.0, -100.0, "Start, USA"),
        (40.0, -100.0, "Finish, USA"),
    ]
    make_station(35.0, -100.0, price=3.00, name="Mid Stop")

    client = APIClient()
    resp = client.post(
        "/api/route-fuel-plan/",
        {"start": "Townville, TX", "finish": "Cityburg, ND"},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    assert mock_geo.call_count == 2  # one per text location, cached thereafter
    assert resp.json()["start"]["lat"] == 30.0


@patch("apps.routes.views.get_route")
def test_routing_failure_returns_424(mock_route):
    mock_route.side_effect = RoutingError("provider down")
    client = APIClient()
    resp = client.post(
        "/api/route-fuel-plan/",
        {
            "start": {"lat": 30.0, "lng": -100.0},
            "finish": {"lat": 40.0, "lng": -100.0},
        },
        format="json",
    )
    assert resp.status_code == 424
    assert resp.json()["error"] == "routing_unavailable"


def test_invalid_payload_returns_400():
    client = APIClient()
    resp = client.post("/api/route-fuel-plan/", {"start": "Dallas, TX"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"


def test_location_outside_usa_returns_400():
    client = APIClient()
    resp = client.post(
        "/api/route-fuel-plan/",
        {
            "start": {"lat": 48.8566, "lng": 2.3522},  # Paris, France
            "finish": {"lat": 32.7767, "lng": -96.7970},
        },
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "location_error"
