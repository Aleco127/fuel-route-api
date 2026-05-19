"""Request-validation tests for the serializer (no DB, no network)."""
from apps.routes.serializers import RouteFuelPlanRequestSerializer


def test_accepts_text_locations():
    s = RouteFuelPlanRequestSerializer(
        data={"start": "Los Angeles, CA", "finish": "Dallas, TX"}
    )
    assert s.is_valid(), s.errors
    assert s.validated_data["start"]["lat"] is None
    assert s.validated_data["start"]["input"] == "Los Angeles, CA"


def test_accepts_coordinate_objects():
    s = RouteFuelPlanRequestSerializer(
        data={
            "start": {"lat": 34.0522, "lng": -118.2437},
            "finish": {"lat": 32.7767, "lng": -96.7970},
        }
    )
    assert s.is_valid(), s.errors
    assert s.validated_data["start"]["lat"] == 34.0522
    assert s.validated_data["finish"]["lng"] == -96.7970


def test_rejects_missing_finish():
    s = RouteFuelPlanRequestSerializer(data={"start": "Dallas, TX"})
    assert not s.is_valid()
    assert "finish" in s.errors


def test_rejects_empty_string():
    s = RouteFuelPlanRequestSerializer(data={"start": "  ", "finish": "Dallas, TX"})
    assert not s.is_valid()
    assert "start" in s.errors


def test_rejects_bad_coordinates():
    s = RouteFuelPlanRequestSerializer(
        data={"start": {"lat": "abc", "lng": 1}, "finish": "Dallas, TX"}
    )
    assert not s.is_valid()


def test_rejects_out_of_range_coordinates():
    s = RouteFuelPlanRequestSerializer(
        data={"start": {"lat": 999, "lng": -100}, "finish": "Dallas, TX"}
    )
    assert not s.is_valid()
