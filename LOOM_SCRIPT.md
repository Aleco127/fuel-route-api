# Loom Walkthrough Script (~5 minutes)

> Goal: prove the API works, the route is fetched efficiently, fuel stops use
> the assessment-provided prices, the 500-mi constraint holds, and the cost
> math is correct — all explainable in under 5 minutes.

---

### 0. Before recording (have ready, NOT on camera)
- Local OSRM container alive: `docker start osrm-texas` → `docker ps`
  should show `osrm-texas` listening on `0.0.0.0:5000`.
- `.env` contains `OSRM_BASE_URL=http://localhost:5000`.
- Real assessment prices already imported (7,531 rows). If not:
  ```powershell
  .venv\Scripts\python.exe manage.py import_fuel_prices `
    --file "C:\Users\aleja\OneDrive\Desktop\fuel-prices-for-be-assessment.csv" --truncate
  ```
- Dev server running: `.venv\Scripts\python.exe manage.py runserver`
- Postman with three saved requests (see step 5).
- VS Code / explorer open at `fuel-route-api/` (for the structure tour).

---

### 1. The challenge (~30 s)
"Given a start and finish in the USA, return the driving route and the
**cheapest** way to fuel a vehicle that does **10 mpg** with a **500-mile
range**, using the assessment's fuel-price file. Constraint from the brief:
minimise external map API calls — I make exactly **one** per request."

### 2. Project structure (~40 s)
Show the tree:
- `apps/routes/services/` → `routing_service`, `geocoding_service`,
  `fuel_optimizer`, `geo_utils` (logic lives here, **not** in views).
- `apps/fuel/` → `FuelStation` model + flexible `import_fuel_prices`
  command + `offline_geocoder` (ZIP-based, no network).
- `apps/routes/views.py` → thin orchestration.
- `tests/` → validation, optimizer, full API (network mocked).

"Clean separation: views orchestrate, services do the work."

### 3. Fuel station import (~40 s)
Show the import command and the parser:
```powershell
.venv\Scripts\python.exe manage.py import_fuel_prices `
  --file "C:\Users\aleja\OneDrive\Desktop\fuel-prices-for-be-assessment.csv" --truncate
```
"The parser auto-detects columns by synonyms — `truckstop name`,
`retail price`, `state`… The assessment file has no coordinates, so I
resolve every US `(city, state)` from a bundled offline ZIP dataset:
**7,531 US stations placed in ~7 seconds with zero network calls**.
Canadian rows are skipped per the USA-only requirement."

### 4. The endpoint (~30 s)
Open `apps/routes/views.py` and `apps/routes/urls.py`:
"`POST /api/route-fuel-plan/`. Validate → resolve coordinates (geocode only
if text, and even then offline first) → **one** OSRM call → optimizer →
persist → respond."

### 5. Run Postman requests (~60 s)
POST `http://127.0.0.1:8000/api/route-fuel-plan/`

**Request A — long route, multi-stop (the headline demo):**
```json
{ "start": "Brownsville, TX", "finish": "Amarillo, TX" }
```
Expected: ~778 mi, **2 fuel stops**, total ≈ $217. "Two stops because the
trip exceeds the 500-mi tank — the optimizer chose the cheapest reachable
stations and guarantees no leg exceeds 500 mi."

**Request B — short route, single stop:**
```json
{ "start": "Dallas, TX", "finish": "Houston, TX" }
```
Expected: ~240 mi, 1 stop, total ≈ $66.

**Request C — coordinates path (skips geocoding entirely):**
```json
{ "start": {"lat": 31.7619, "lng": -106.4850},
  "finish": {"lat": 29.7604, "lng": -95.3698} }
```
Expected: El Paso → Houston, ~743 mi, 1 stop, total ≈ $217. "Coordinates
add zero extra calls — no geocoding needed."

### 6. Explain the response (~50 s)
Point at:
- `route.distance_miles`, `duration_minutes`, `geometry` (GeoJSON), and
  `map_provider: OSRM`.
- `fuel_plan[]` for each stop: `station_name`, `state`,
  `price_per_gallon` (real prices from the assessment file),
  `distance_from_start_miles`, `gallons_purchased`, `estimated_cost`.
- `total_fuel_cost`, `route_feasible`, `notes[]`.
- "Notice gaps between consecutive stops are all ≤ 500 mi — the
  500-mi range constraint is structurally enforced."
- "Σ gallons = distance ÷ 10 exactly, so the cost math is consistent."

### 7. Optimization logic & API-call minimisation (~50 s)
Open `apps/routes/services/fuel_optimizer.py`:
"Decode the geometry from the **single** OSRM call → cumulative distance
→ resample the route every ~3 mi → **one** bounding-box DB query for
stations in the corridor → snap stations to the route → greedy: within
each 500-mi tank window pick the **cheapest** reachable station,
jump there, repeat until the destination is in range. That structurally
guarantees no leg exceeds 500 mi. Total fuel = distance ÷ mpg; the
optimizer only chooses *where* it's bought. The single routing call is
cached for 30 min; geocoding is offline-first via the bundled ZIP
dataset, with Nominatim as a fallback."

### 8. Edge cases & tests (~30 s)
```powershell
.venv\Scripts\python.exe -m pytest -q
```
"**16 passed**. Tests cover validation, short vs long routes, the
range constraint never breaking, cheapest-station choice, missing
stations, routing failure → 424, and out-of-USA → 400. Network is
mocked so tests are fast and deterministic."

### Close (~10 s)
"No API keys required, exactly one routing call per request, clean
service layer, fully tested. Repo: github.com/Aleco127/fuel-route-api.
Thanks."

---

### Demo cheatsheet (Texas routes, validated end-to-end offline)

| Input | Distance | Stops | Total |
|---|---|---|---|
| `Brownsville, TX` → `Amarillo, TX` | 778 mi | **2** | ~$217 |
| `El Paso, TX` → `Houston, TX` | 743 mi | 1 | ~$217 |
| `Dallas, TX` → `Houston, TX` | 240 mi | 1 | ~$66 |

> Local OSRM is a **Texas extract**. Cross-state routes (e.g. the original
> "Los Angeles → Dallas" example) require processing the full US PBF
> (~10 GB) — out of scope for the Loom; the algorithm is identical.
