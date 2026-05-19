"""Request/response serialisers for the route-fuel-plan endpoint."""
from __future__ import annotations

from rest_framework import serializers


class LocationField(serializers.Field):
    """Accepts EITHER a text location ("Los Angeles, CA") OR {lat, lng}.

    Normalises both shapes to a dict::

        {"input": <str>, "lat": <float|None>, "lng": <float|None>}

    Text inputs leave lat/lng as None so the view knows it must geocode.
    """

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                raise serializers.ValidationError("Location text cannot be empty.")
            return {"input": text, "lat": None, "lng": None}

        if isinstance(data, dict):
            if "lat" not in data or ("lng" not in data and "lon" not in data):
                raise serializers.ValidationError(
                    "Coordinate object must include 'lat' and 'lng'."
                )
            try:
                lat = float(data["lat"])
                lng = float(data["lng"] if "lng" in data else data["lon"])
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    "'lat' and 'lng' must be numbers."
                )
            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                raise serializers.ValidationError(
                    "'lat'/'lng' are out of valid range."
                )
            return {
                "input": f"{lat},{lng}",
                "lat": lat,
                "lng": lng,
            }

        raise serializers.ValidationError(
            "Location must be a string or an object with 'lat' and 'lng'."
        )

    def to_representation(self, value):
        return value


class RouteFuelPlanRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()
