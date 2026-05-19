# Fuel Route API

A Django REST API that, given a **start** and **finish** in the USA, returns
the driving route plus a **cost-optimised fuel plan**: where to stop, how
many gallons to buy, and the total fuel cost — assuming a vehicle with a
**500-mile range** and **10 mpg**.

* One endpoint: `POST /api/route-fuel-plan/`
* **Zero API keys required** — OSRM (routing) and Nominatim (geocoding) are
  free, no-key services.
* **One** routing API call per request (geometry + distance + duration in a
  single response), cached for repeats.
* SQLite, so a reviewer can run it in under a minute.

---

## 1. Setup

```bash
cd fuel-route-api

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env        # optional — everything has safe defaults
```

Latest stable Django (5.2 LTS) is pinned in `requirements.txt`.

## 2. Migrate the database

```bash
python manage.py migrate
```

## 3. Import fuel prices

A ready-to-use sample file is bundled so the demo works immediately:

```bash
python manage.py import_fuel_prices --file apps/fuel/data/sample_fuel_prices.csv
```

To load the assessment's real fuel-price file
(`fuel-prices-for-be-assessment.csv`, ~8k rows, no coordinates):

```bash
python manage.py import_fuel_prices \
  --file /path/to/fuel-prices-for-be-assessment.csv --truncate
```

That's it — **~7 seconds, no network calls**. The parser auto-detects
columns via a synonym table (`truckstop name`, `retail price`, `state`…).
Because that file has **no coordinates**, the importer resolves every US
`(city, state)` from a bundled offline ZIP database (`zipcodes`): in
practice it places **100% of the US stations** (7,531/7,531) instantly and
deterministically. Non-US rows (Canadian provinces) are skipped per the
USA-only requirement.

Flags:
* `--geocode` — additionally refine leftover rows online via Nominatim
  (deduplicated + cached; rarely needed since offline covers ~100%).
* `--no-offline-geocode` — disable the offline resolver (not recommended).
* Files that already include `latitude`/`longitude` columns are used as-is.

## 4. Run the server

```bash
python manage.py runserver
```

Health check: `GET http://127.0.0.1:8000/` → `{"status": "ok"}`

By default the app uses the **public OSRM demo** (no key, internet
required). Text inputs like `"Houston, TX"` are resolved by the **offline**
ZIP geocoder first (instant, no network); Nominatim is only a fallback for
free-form addresses.

### Optional: run OSRM locally (offline, no rate limits)

For a fully offline demo (or to avoid the public demo's rate limits), run
OSRM in Docker — see `docker-compose.yml` for the one-time graph-prep
commands (a regional extract such as Texas is ~700 MB, ~10 min). Then:

```bash
OSRM_DATA=./osrm-data docker compose up -d        # serves :5000
echo "OSRM_BASE_URL=http://localhost:5000" >> .env
```

With a Texas extract + offline geocoding the API needs **zero internet**
(e.g. `El Paso, TX` → `Houston, TX`, `Brownsville, TX` → `Amarillo, TX`).

## 5. Example requests

### A) Text locations

```bash
curl -X POST http://127.0.0.1:8000/api/route-fuel-plan/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Los Angeles, CA", "finish": "Dallas, TX"}'
```

### B) Coordinates (no geocoding call)

```bash
curl -X POST http://127.0.0.1:8000/api/route-fuel-plan/ \
  -H "Content-Type: application/json" \
  -d '{"start": {"lat": 34.0522, "lng": -118.2437},
       "finish": {"lat": 32.7767, "lng": -96.7970}}'
```

### Example response (truncated)

```json
{
  "start": {"input": "Los Angeles, CA", "lat": 34.0522, "lng": -118.2437},
  "finish": {"input": "Dallas, TX", "lat": 32.7767, "lng": -96.7970},
  "route": {
    "distance_miles": 1435.2,
    "duration_minutes": 1260.0,
    "geometry": {"type": "LineString", "coordinates": [[-118.24, 34.05], ...]},
    "map_provider": "OSRM"
  },
  "vehicle": {"max_range_miles": 500, "mpg": 10, "tank_capacity_gallons": 50.0},
  "fuel_plan": [
    {
      "stop_number": 1,
      "station_name": "Quartzsite Truck Plaza",
      "city": "Quartzsite", "state": "AZ",
      "lat": 33.6639, "lng": -114.23,
      "price_per_gallon": 3.62,
      "distance_from_start_miles": 421.5,
      "gallons_purchased": 42.15,
      "estimated_cost": 152.58
    }
  ],
  "total_fuel_cost": 502.30,
  "route_feasible": true,
  "notes": ["Total fuel for the trip = distance / mpg; ...", "..."]
}
```

## 6. Tests

```bash
pytest
```

Covers: request validation, short route (<500 mi), long route requiring
multiple stops, fuel-cost math, the **range constraint is never violated**,
cheapest-station selection, missing candidates, routing failure (424),
out-of-USA rejection, and the full HTTP flow with the network mocked.

---

## Optimization algorithm (how it works)

1. **One** routing call → distance, duration, full geometry.
2. Decode geometry into ordered coordinates; compute cumulative distance.
3. Resample the route to a fine, bounded set of points (~3 mi apart) so
   on-route stations are never missed and the snap loop stays fast.
4. **One** DB query: stations inside the route's bounding box (padded by the
   search radius). We never test every station against every route point.
5. Snap each station to its nearest sample point; keep it if within ~15 mi
   of the route. Its `distance_from_start` is that point's cumulative
   distance (accurate to a few miles).
6. **Greedy walk**: from the current mile, look ahead one tank (500 mi);
   among reachable stations pick the **cheapest** (preferring legs ≥ 50 mi so
   stops don't cluster), jump to it, repeat until the destination is within
   range. This guarantees **no leg ever exceeds 500 mi**.
7. **Fuel math**: total fuel for the trip is exactly `distance / mpg`; the
   optimizer only decides *where* it is bought. Each stop buys enough to
   reach the next stop / destination. `cost = gallons × station price`.

**Fuel assumption:** the vehicle departs with an **empty tank**, so a
station must exist within 500 mi of the start; the start→first-stop fuel is
purchased at the first stop.

All knobs (`CHECKPOINT_SPACING_MILES`, `STATION_SEARCH_RADIUS_MILES`,
`MIN_LEG_MILES`, range, mpg) are environment-configurable.

## Performance notes

* Coordinate inputs ⇒ **0 geocoding calls**; text inputs are geocoded once
  and cached (process cache + `GeocodeCache` table).
* Exactly **1 routing call** per unique route; identical routes are served
  from a 30-min process cache.
* Station lookup = **1 indexed bounding-box query** + checkpoint snap, not an
  O(stations × route-points) scan.
* Every `RoutePlan` is persisted (with full response JSON) for replay/audit
  without re-calling the routing API.

## Known limitations / assumptions

* `distance_from_start` is snapped to a ~3-mi route resample — accurate for
  stop selection, not a turn-by-turn fuel gauge.
* The greedy heuristic is cost-aware and deterministic but **not provably
  globally optimal** (the brief explicitly allows this).
* OSRM public demo / Nominatim are rate-limited shared services; for
  production use a hosted instance or paid tier.
* The assessment file has no coordinates; stations are placed at their
  **city centroid** (offline ZIP dataset). That is well within the 15-mi
  match radius for interstate truck stops but is not the exact pump
  location. `--geocode` can refine via Nominatim if ever needed.
* USA validity is a continental bounding box, not a polygon (Alaska/Hawaii
  out-of-box driving routes are not supported by OSRM anyway).

See `LOOM_SCRIPT.md` for the 5-minute walkthrough.
