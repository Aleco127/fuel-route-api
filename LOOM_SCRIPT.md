# Loom Walkthrough Script (~5 minutes)

> Goal: prove the API works, the route is fetched efficiently, fuel stops use
> the provided prices, the 500-mi constraint holds, and the cost math is
> correct — all explainable in under 5 minutes.

---

### 0. Before recording (have ready)
- Server running: `python manage.py runserver`
- Sample data imported
- Postman with two saved requests (text + coordinates)

---

### 1. The challenge (~30 s)
"Given a start and finish in the USA, return the driving route and the
**cheapest** way to fuel a vehicle that does **10 mpg** with a **500-mile
range**. Constraint from the brief: minimise external map API calls — I make
exactly **one** per request."

### 2. Project structure (~40 s)
Show the tree:
- `apps/routes/services/` → `routing_service`, `geocoding_service`,
  `fuel_optimizer`, `geo_utils` (logic lives here, **not** in views).
- `apps/fuel/` → `FuelStation` model + flexible `import_fuel_prices` command.
- `apps/routes/views.py` → thin orchestration.
- `tests/` → validation, optimizer, full API.
"Clean separation: views orchestrate, services do the work."

### 3. Fuel station import (~40 s)
```bash
python manage.py import_fuel_prices --file apps/fuel/data/sample_fuel_prices.csv
```
"The parser maps column synonyms automatically — `retail price`,
`truckstop name`, `lat`/`latitude`… If a file has no coordinates I fall back
to state centroids, or `--geocode` resolves real ones, deduped and cached."

### 4. The endpoint (~30 s)
Open `apps/routes/views.py`: "Validate → resolve coordinates (geocode only if
text) → **one** OSRM call → optimizer → persist → respond."

### 5. Run a Postman request (~50 s)
POST `/api/route-fuel-plan/`
```json
{ "start": "Los Angeles, CA", "finish": "Dallas, TX" }
```
Then show the coordinate variant — "coordinates skip geocoding entirely, zero
extra calls."

### 6. Explain the response (~50 s)
Point at:
- `route.distance_miles`, `duration_minutes`, `geometry`, `map_provider:OSRM`.
- `fuel_plan[]`: station, `price_per_gallon`, `distance_from_start_miles`,
  `gallons_purchased`, `estimated_cost`.
- `total_fuel_cost`, `route_feasible`, `notes`.

### 7. Optimization logic & API-call minimisation (~50 s)
"Decode geometry → cumulative distance → fine route resample → **one**
bounding-box DB query → snap stations to the route → greedy: within each
500-mi tank window pick the **cheapest** reachable station, jump there,
repeat until the destination is in range. That guarantees no leg exceeds
500 mi. Total fuel = distance ÷ mpg; the optimizer only chooses *where* it's
bought. One routing call, cached; geocoding cached too."

### 8. Edge cases & tests (~30 s)
```bash
pytest -q
```
"Tests cover validation, short vs long routes, the range constraint never
breaking, cheapest-station choice, missing stations, routing failure → 424,
and out-of-USA → 400. Network is mocked so tests are fast and deterministic."

### Close (~10 s)
"No API keys, one routing call, clean service layer, fully tested. Thanks."
