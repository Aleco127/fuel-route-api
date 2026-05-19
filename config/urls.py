from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "service": "fuel-route-api"})


urlpatterns = [
    path("", health),
    path("api/", include("apps.routes.urls")),
]
