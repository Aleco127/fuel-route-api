from django.contrib import admin

from .models import RoutePlan


@admin.register(RoutePlan)
class RoutePlanAdmin(admin.ModelAdmin):
    list_display = (
        "start_input",
        "finish_input",
        "distance_miles",
        "total_fuel_cost",
        "created_at",
    )
    search_fields = ("start_input", "finish_input")
    readonly_fields = ("response_json", "created_at")
