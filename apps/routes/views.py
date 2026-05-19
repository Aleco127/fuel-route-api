"""
HTTP layer for POST /api/route-fuel-plan/.

The view is deliberately thin: validate -> resolve coords -> one routing
call -> optimizer -> persist -> respond. All real logic lives in services.
"""
from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler

from .models import RoutePlan
from .serializers import RouteFuelPlanRequestSerializer
from .services.fuel_optimizer import optimize_fuel_plan
from .services.geocoding_service import GeocodingError, geocode_text
from .services.routing_service import RoutingError, get_route

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    """Return clean JSON for unexpected errors instead of HTML 500s."""
    response = exception_handler(exc, context)
    if response is not None:
        return response
    logger.exception("Unhandled error in %s", context.get("view"))
    return Response(
        {"error": "internal_error", "detail": "An unexpected error occurred."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _within_usa(lat: float, lng: float) -> bool:
    b = settings.USA_BBOX
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lng"] <= lng <= b["max_lng"]


def _resolve_location(loc: dict, label: str) -> dict:
    """Turn a validated location into {input, lat, lng}, geocoding if needed.

    Geocoding only happens for text input; coordinate input costs 0 calls.
    """
    if loc["lat"] is not None and loc["lng"] is not None:
        lat, lng = loc["lat"], loc["lng"]
    else:
        try:
            lat, lng, _display = geocode_text(loc["input"])
        except GeocodingError as exc:
            raise _ApiError(
                f"Could not geocode {label} location '{loc['input']}'.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            ) from exc

    if not _within_usa(lat, lng):
        raise _ApiError(
            f"The {label} location is outside the supported USA area.",
            status.HTTP_400_BAD_REQUEST,
        )
    return {"input": loc["input"], "lat": lat, "lng": lng}


class _ApiError(Exception):
    def __init__(self, detail: str, http_status: int):
        super().__init__(detail)
        self.detail = detail
        self.http_status = http_status


class RouteFuelPlanView(APIView):
    """Compute a route and a cost-optimised fuel plan between two US points."""

    def post(self, request):
        serializer = RouteFuelPlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "invalid_request", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        try:
            start = _resolve_location(data["start"], "start")
            finish = _resolve_location(data["finish"], "finish")

            # Exactly ONE external routing call (geometry + distance).
            route = get_route(
                start["lat"], start["lng"], finish["lat"], finish["lng"]
            )
        except _ApiError as exc:
            return Response(
                {"error": "location_error", "detail": exc.detail},
                status=exc.http_status,
            )
        except RoutingError as exc:
            return Response(
                {"error": "routing_unavailable", "detail": str(exc)},
                status=status.HTTP_424_FAILED_DEPENDENCY,
            )

        plan = optimize_fuel_plan(route.coordinates, route.distance_miles)

        notes = [
            "Total fuel for the trip = distance / mpg; the optimizer only "
            "chooses WHERE fuel is bought to minimise cost.",
            f"Vehicle range assumed {settings.VEHICLE_MAX_RANGE_MILES:.0f} mi "
            f"at {settings.VEHICLE_MPG:.0f} mpg (empty tank at start).",
            "Fuel stops are stations within "
            f"{settings.STATION_SEARCH_RADIUS_MILES:.0f} mi of the route, "
            "snapped to it to estimate distance_from_start.",
        ]
        notes.extend(plan.notes)

        payload = {
            "start": start,
            "finish": finish,
            "route": {
                "distance_miles": round(route.distance_miles, 2),
                "duration_minutes": round(route.duration_minutes, 1),
                "geometry": route.geometry,
                "map_provider": route.provider,
            },
            "vehicle": {
                "max_range_miles": settings.VEHICLE_MAX_RANGE_MILES,
                "mpg": settings.VEHICLE_MPG,
                "tank_capacity_gallons": round(
                    settings.VEHICLE_TANK_CAPACITY_GALLONS, 2
                ),
            },
            "fuel_plan": plan.stops,
            "total_fuel_cost": plan.total_fuel_cost,
            "route_feasible": plan.feasible,
            "notes": notes,
        }

        # Persist for audit / replay (does not re-hit the routing API).
        RoutePlan.objects.create(
            start_input=start["input"],
            finish_input=finish["input"],
            start_lat=start["lat"],
            start_lng=start["lng"],
            finish_lat=finish["lat"],
            finish_lng=finish["lng"],
            distance_miles=round(route.distance_miles, 2),
            total_fuel_cost=plan.total_fuel_cost,
            response_json=payload,
        )
        return Response(payload, status=status.HTTP_200_OK)
