"""
Django settings for the Fuel Route API.

The project is intentionally self-contained: SQLite database, no external
API keys required, sane defaults for every tunable so a reviewer can clone
and run it in under a minute.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present (optional - everything has defaults).
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Core Django ----------------------------------------------------------
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.fuel",
    "apps.routes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# In-process cache is enough for geocoding/route memoisation in a single
# assessment instance. Swap for Redis in production.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route-api",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "static/"
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "EXCEPTION_HANDLER": "apps.routes.views.api_exception_handler",
}

# --- Domain configuration -------------------------------------------------
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org")
ROUTING_TIMEOUT_SECONDS = _env_float("ROUTING_TIMEOUT_SECONDS", 20)

NOMINATIM_BASE_URL = os.getenv(
    "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"
)
GEOCODER_USER_AGENT = os.getenv(
    "GEOCODER_USER_AGENT", "fuel-route-api/1.0 (assessment@example.com)"
)
GEOCODING_TIMEOUT_SECONDS = _env_float("GEOCODING_TIMEOUT_SECONDS", 15)

VEHICLE_MAX_RANGE_MILES = _env_float("VEHICLE_MAX_RANGE_MILES", 500)
VEHICLE_MPG = _env_float("VEHICLE_MPG", 10)
VEHICLE_TANK_CAPACITY_GALLONS = VEHICLE_MAX_RANGE_MILES / VEHICLE_MPG

STATION_SEARCH_RADIUS_MILES = _env_float("STATION_SEARCH_RADIUS_MILES", 15)
MIN_LEG_MILES = _env_float("MIN_LEG_MILES", 50)

# Continental-USA bounding box used to reject out-of-country locations.
USA_BBOX = {"min_lat": 24.0, "max_lat": 49.5, "min_lng": -125.0, "max_lng": -66.5}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
