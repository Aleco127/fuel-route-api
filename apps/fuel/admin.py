from django.contrib import admin

from .models import FuelStation, GeocodeCache


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "price_per_gallon", "is_approximate_location")
    list_filter = ("state", "is_approximate_location")
    search_fields = ("name", "city", "address", "source_id")


@admin.register(GeocodeCache)
class GeocodeCacheAdmin(admin.ModelAdmin):
    list_display = ("query", "latitude", "longitude", "created_at")
    search_fields = ("query",)
