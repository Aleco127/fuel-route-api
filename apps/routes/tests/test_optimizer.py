"""Algorithm tests: range constraint, cost math, station selection."""
import pytest

from apps.routes.services.fuel_optimizer import optimize_fuel_plan
from apps.routes.services.geo_utils import cumulative_distances

from .conftest import straight_route

pytestmark = pytest.mark.django_db


def _total_miles(route):
    return cumulative_distances(route)[-1]


def test_short_route_single_cheapest_stop(make_station):
    # ~210 mi route (well under the 500 mi range).
    route = straight_route(30.0, 33.0)
    total = _total_miles(route)
    assert total < 500
    make_station(31.0, -100.0, price=4.00, name="Pricey")
    make_station(32.0, -100.0, price=3.00, name="Cheap")

    plan = optimize_fuel_plan(route, total)

    assert len(plan.stops) == 1
    assert plan.stops[0]["station_name"] == "Cheap"
    # Whole-trip fuel bought once: gallons == distance / mpg (mpg=10).
    assert plan.stops[0]["gallons_purchased"] == pytest.approx(total / 10, rel=0.05)
    assert plan.total_fuel_cost == pytest.approx((total / 10) * 3.00, rel=0.05)


def test_long_route_never_exceeds_range(make_station):
    # ~1035 mi route -> must refuel multiple times within 500 mi range.
    route = straight_route(30.0, 45.0)
    total = _total_miles(route)
    assert total > 1000
    # A station roughly every ~140 mi (every 2 deg of latitude).
    for i, lat in enumerate(range(31, 45, 2)):
        make_station(float(lat), -100.0, price=3.0 + (i % 3) * 0.1, name=f"St{lat}")

    plan = optimize_fuel_plan(route, total)

    assert plan.feasible
    assert len(plan.stops) >= 2
    marks = [0.0] + [s["distance_from_start_miles"] for s in plan.stops] + [total]
    gaps = [b - a for a, b in zip(marks, marks[1:])]
    assert max(gaps) <= 500 + 1e-6  # core safety constraint

    total_gallons = sum(s["gallons_purchased"] for s in plan.stops)
    assert total_gallons == pytest.approx(total / 10, rel=0.05)


def test_prefers_cheaper_reachable_station(make_station):
    route = straight_route(30.0, 40.0)  # ~690 mi
    total = _total_miles(route)
    make_station(34.0, -100.0, price=4.50, name="Expensive")
    make_station(35.0, -100.0, price=2.90, name="Bargain")  # both within 500 mi

    plan = optimize_fuel_plan(route, total)

    assert plan.stops[0]["station_name"] == "Bargain"


def test_no_stations_returns_note_and_no_cost(db):
    route = straight_route(30.0, 33.0)
    total = _total_miles(route)

    plan = optimize_fuel_plan(route, total)

    assert plan.stops == []
    assert plan.total_fuel_cost is None
    assert any("No fuel stations" in n for n in plan.notes)


def test_infeasible_when_gap_exceeds_range(make_station):
    # Long route but the only station sits in the first 100 mi -> the
    # remaining >500 mi gap is not coverable.
    route = straight_route(30.0, 42.0)  # ~828 mi
    total = _total_miles(route)
    make_station(31.0, -100.0, price=3.0, name="OnlyEarly")

    plan = optimize_fuel_plan(route, total)

    assert plan.feasible is False
    assert any("not be completable" in n for n in plan.notes)
