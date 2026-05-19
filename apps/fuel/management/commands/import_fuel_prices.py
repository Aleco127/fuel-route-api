"""
Import fuel stations from the assessment's fuel-price file.

Examples
--------
    python manage.py import_fuel_prices --file apps/fuel/data/sample_fuel_prices.csv
    python manage.py import_fuel_prices --file fuel-prices.csv --truncate
    python manage.py import_fuel_prices --file opis_truckstops.csv --geocode

`--geocode` resolves real coordinates for files that lack lat/lng. It
deduplicates by (city, state) so an 8k-row file only triggers a few hundred
geocoder calls, all persisted in GeocodeCache for reuse.
"""
from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.fuel.models import FuelStation
from apps.fuel.services.fuel_parser import FuelFileError, parse_fuel_file

DEFAULT_FILE = Path(settings.BASE_DIR) / "apps" / "fuel" / "data" / "sample_fuel_prices.csv"


class Command(BaseCommand):
    help = "Import fuel stations and prices from a CSV/XLSX file."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--file",
            default=str(DEFAULT_FILE),
            help="Path to the fuel-price CSV/XLSX (defaults to the bundled sample).",
        )
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing FuelStation rows before importing.",
        )
        parser.add_argument(
            "--no-offline-geocode",
            action="store_true",
            help="Skip the offline ZIP-based geocoder (not recommended).",
        )
        parser.add_argument(
            "--geocode",
            action="store_true",
            help="Also resolve any leftover rows online via Nominatim (cached).",
        )

    def handle(self, *args, **options) -> None:
        file_path = options["file"]
        try:
            stations = parse_fuel_file(file_path)
        except FuelFileError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Parsed {len(stations)} station rows from {file_path}")

        # Default path: instant, offline, city-level coordinates (no network).
        if not options["no_offline_geocode"]:
            self._geocode_offline(stations)

        # Optional: online fallback for the residue (e.g. odd name variants).
        if options["geocode"]:
            self._geocode_approximate(stations)

        with transaction.atomic():
            if options["truncate"]:
                deleted, _ = FuelStation.objects.all().delete()
                self.stdout.write(f"Truncated existing stations ({deleted} rows).")

            objs = [
                FuelStation(
                    name=s.name,
                    brand=s.brand,
                    address=s.address,
                    city=s.city,
                    state=s.state,
                    latitude=s.latitude,
                    longitude=s.longitude,
                    price_per_gallon=s.price_per_gallon,
                    is_approximate_location=s.is_approximate_location,
                    source_id=s.source_id,
                )
                for s in stations
            ]
            FuelStation.objects.bulk_create(objs, batch_size=1000)

        approx = sum(1 for s in stations if s.is_approximate_location)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(stations)} stations "
                f"({approx} with approximate/centroid coordinates)."
            )
        )
        if approx:
            self.stdout.write(
                self.style.WARNING(
                    f"{approx} rows still use a coarse state centroid "
                    "(unresolved city). Re-run with --geocode to refine."
                )
            )

    def _geocode_offline(self, stations) -> None:
        """Resolve (city, state) -> coords from the offline ZIP dataset.

        No network, deterministic, resolves ~98% of the assessment file in
        seconds. Unresolved rows keep their state-centroid fallback.
        """
        from apps.fuel.services.offline_geocoder import geocode_city_state

        to_fix = [s for s in stations if s.is_approximate_location and s.city]
        cache: dict[tuple[str, str], tuple[float, float] | None] = {}
        resolved = 0
        for s in to_fix:
            key = (s.city.strip().upper(), s.state.strip().upper())
            if key not in cache:
                cache[key] = geocode_city_state(s.city, s.state)
            point = cache[key]
            if point:
                s.latitude, s.longitude = point
                s.is_approximate_location = False
                resolved += 1
        self.stdout.write(
            f"Offline geocoder resolved {resolved}/{len(to_fix)} rows "
            f"({len(cache)} unique cities) with no network calls."
        )

    def _geocode_approximate(self, stations) -> None:
        """Resolve (city, state) -> coords for approximate rows, deduped."""
        from apps.routes.services.geocoding_service import (
            GeocodingError,
            geocode_text,
        )

        to_fix = [s for s in stations if s.is_approximate_location and s.city]
        unique_keys = sorted({f"{s.city}, {s.state}, USA" for s in to_fix})
        self.stdout.write(
            f"Geocoding {len(unique_keys)} unique (city, state) pairs "
            f"for {len(to_fix)} approximate rows..."
        )
        resolved: dict[str, tuple[float, float]] = {}
        for i, query in enumerate(unique_keys, 1):
            try:
                lat, lng, _ = geocode_text(query)
                resolved[query] = (lat, lng)
            except GeocodingError:
                self.stdout.write(self.style.WARNING(f"  could not geocode: {query}"))
            # Nominatim policy: max ~1 request/second. Cached hits are instant.
            if i % 25 == 0:
                self.stdout.write(f"  geocoded {i}/{len(unique_keys)}")
            time.sleep(1.0)

        for s in to_fix:
            key = f"{s.city}, {s.state}, USA"
            if key in resolved:
                s.latitude, s.longitude = resolved[key]
                s.is_approximate_location = False
