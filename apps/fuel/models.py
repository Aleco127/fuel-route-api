from django.db import models


class FuelStation(models.Model):
    """A single fuel station with its retail price.

    Latitude / longitude are indexed so the optimizer can do a fast
    bounding-box prefilter before computing exact haversine distances.
    """

    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=255, null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=128, null=True, blank=True)
    state = models.CharField(max_length=8, db_index=True)
    latitude = models.FloatField(db_index=True)
    longitude = models.FloatField(db_index=True)
    price_per_gallon = models.FloatField()
    # Whether lat/lng were geocoded/approximated rather than supplied.
    is_approximate_location = models.BooleanField(default=False)
    source_id = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["latitude", "longitude"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.price_per_gallon}"


class GeocodeCache(models.Model):
    """Persistent cache for geocoded text queries (Nominatim).

    Keeps external geocoding calls to the bare minimum across requests
    and across `import_fuel_prices --geocode` runs.
    """

    query = models.CharField(max_length=512, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    display_name = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.query} -> ({self.latitude}, {self.longitude})"
