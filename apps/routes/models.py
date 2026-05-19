from django.db import models


class RoutePlan(models.Model):
    """Audit log of every computed route + fuel plan.

    The full response is stored as JSON so a result can be replayed or
    inspected without recomputing (and without re-hitting the routing API).
    """

    start_input = models.CharField(max_length=255)
    finish_input = models.CharField(max_length=255)
    start_lat = models.FloatField()
    start_lng = models.FloatField()
    finish_lat = models.FloatField()
    finish_lng = models.FloatField()
    distance_miles = models.FloatField()
    total_fuel_cost = models.FloatField(null=True, blank=True)
    response_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.start_input} -> {self.finish_input} ({self.distance_miles} mi)"
