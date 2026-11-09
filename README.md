# Tick Sightings API

A Django REST API that ingests UK tick sighting records from the Elanco student placement API, stores them locally, and exposes search, filtering and aggregate reporting endpoints.

Built for the Elanco ITSP 2026 Backend task.

> **Note:** This uses the educational API at `https://dev-task.elancoapps.com/`. It is not an official source of tick data.

## Contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Setup](#setup)
- [Importing data](#importing-data)
- [Running the API](#running-the-api)
- [API reference](#api-reference)
- [Design decisions](#design-decisions)
- [Data findings](#data-findings)
- [Error handling](#error-handling)
- [Testing](#testing)
- [Limitations and future work](#limitations-and-future-work)

## Features

- **Idempotent importer:** a management command that fetches the upstream data, validates it, and upserts it. Re-running it never creates duplicates.
- **Search and filtering:** filter sightings by city, species and date range; free-text search; ordering; pagination.
- **Reports:** sightings per city, per region, and over time (weekly or monthly), all of which accept the same filters as the list endpoint.
- **Interactive docs:** Swagger UI generated from the code.

## Tech stack

- Python 3.10
- Django (4.1+ is required for `bulk_create(update_conflicts=True)`)
- Django REST Framework
- django-filter
- drf-spectacular (OpenAPI / Swagger)
- SQLite (the default; see [Design decisions](#design-decisions))

## Setup

```bash
# 1. Clone
git clone https://github.com/NomalTWM/TickSightings.git TickSightings
cd TickSightings

# 2. Create and activate a virtual environment
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create the database tables
python manage.py migrate
```

## Importing data

```bash
python manage.py import_sightings
```

Example output on a first run:

```
1000 fetched | 1000 created | 0 already present (refreshed) | 0 duplicates in feed | 0 rejected
```

Running it again leaves the row count unchanged:

```
1000 fetched | 0 created | 1000 already present (refreshed) | 0 duplicates in feed | 0 rejected
```

What the importer does:

1. Fetches `GET /data/tick-sightings` with a timeout and automatic retries (with backoff) on 429/5xx responses.
2. Validates every record: all required fields present and non-empty, and the date parseable.
3. Normalises values: whitespace is trimmed, city names are title-cased, and naive timestamps are treated as UTC.
4. De-duplicates on the upstream `id`.
5. Upserts into the database, so repeated runs are safe.
6. Reports how many records were created, refreshed, duplicated or rejected, and prints the first few rejected records with the reason.

## Running the API

```bash
python manage.py runserver
```

- Swagger UI: http://127.0.0.1:8000/api/docs/
- OpenAPI schema: http://127.0.0.1:8000/api/schema/

## API reference

All endpoints are read-only `GET` requests.

### `GET /api/sightings/`

List sightings (50 per page, newest first by default).

| Parameter | Description | Example |
|---|---|---|
| `location` | City name, case-insensitive exact match | `?location=london` |
| `species` | Species name, case-insensitive exact match | `?species=Marsh tick` |
| `date_from` | Sightings on or after this date (`YYYY-MM-DD`) | `?date_from=2020-01-01` |
| `date_to` | Sightings on or before this date (`YYYY-MM-DD`) | `?date_to=2022-12-31` |
| `search` | Free-text search across city, species and Latin name | `?search=ixodes` |
| `ordering` | Sort field; prefix with `-` for descending | `?ordering=-date` |
| `page` | Page number | `?page=2` |

### `GET /api/sightings/{id}/`

Retrieve one sighting.

### `GET /api/reports/by-city/`

Sighting counts per city, highest first. Accepts the same filters as the list endpoint (`species`, `date_from`, `date_to` and so on).

```json
[
  {"location": "Nottingham", "count": 95},
  {"location": "Birmingham", "count": 82}
]
```

### `GET /api/reports/by-region/`

Sighting counts per UK region. The upstream data only contains cities, so cities are mapped to regions in `tickSightings/regions.py`. Any city missing from the mapping is reported under `"Unknown"` so gaps are visible. Accepts the same filters as the list endpoint.

### `GET /api/reports/trends/?interval=weekly|monthly`

Sighting counts over time. `interval` defaults to `monthly`. Any other value returns `400`. Accepts the same filters as the list endpoint.

```json
[
  {"period": "2012-01-01", "count": 7},
  {"period": "2012-02-01", "count": 5}
]
```

### Example requests

```bash
curl "http://127.0.0.1:8000/api/sightings/?location=glasgow&date_from=2020-01-01"
curl "http://127.0.0.1:8000/api/reports/by-region/?species=Marsh%20tick"
curl "http://127.0.0.1:8000/api/reports/trends/?interval=weekly&location=Glasgow"
curl "http://127.0.0.1:8000/api/reports/trends/?interval=daily"   # -> 400
```

## Design decisions

**Local copy of the data instead of proxying the upstream API.** The importer stores records in the app's own database. This makes filtering and aggregation fast SQL queries, keeps the API available if the upstream is down, and means report endpoints don't depend on a third party at request time. The trade-off is that data can become stale between imports, which is why the importer is cheap and safe to re-run.

**Idempotent upserts keyed on the upstream ID.** The upstream `id` is unique and stable in the data I inspected (1,000 records, no duplicates), so it is the natural key. [**Edit to match your model:** *The model uses the upstream `id` as its primary key.* **or** *The model keeps Django's auto primary key and stores the upstream ID in a unique `external_id` column.*] With multiple data sources, I would switch to a surrogate key plus a unique `(source, external_id)` constraint.

**Region mapping is explicit.** The feed has no region field, so `regions.py` maps cities to regions. Unmapped cities fall into `"Unknown"` instead of being dropped silently.

**Time handling.** Upstream timestamps carry no timezone. They are treated as UTC, and weekly/monthly grouping uses UTC boundaries.

**Reports share the list endpoint's filters.** Both are built on the same `FilterSet`, so any filter works consistently across the list and every report.

**SQLite.** It keeps setup to a single command. The ORM code is database-agnostic, so moving to PostgreSQL only needs a settings change.

## Data findings

I profiled the upstream data before designing the importer:

- 1,000 records, which matches `total_sightings` from `GET /data/stats`.
- No nulls, empty strings, duplicate IDs, or unparseable dates in the current feed.
- 14 UK cities, 5 species, and each species maps to exactly one Latin name.
- Dates range from 2012-01-03 to 2024-12-30.
- Records are spread fairly evenly across cities and species.

The current feed is clean, but the importer validates and de-duplicates anyway, because the upstream is a third-party source that may change.

## Error handling

- **Upstream failures:** timeouts, retries with backoff on 429/5xx, and a clear error from the import command if the API is unreachable. Existing data in the database is left untouched when an import fails.
- **Bad records:** records with missing fields or unparseable dates are skipped and reported with the reason, without aborting the whole import.
- **Bad requests:** invalid filter values (for example a malformed date) and an invalid `interval` return `400` with a descriptive message.

## Testing
 
```bash
python manage.py test tickSightings
```
 
Add `-v 2` to see each test by name. The suite has 33 tests in `tickSightings/tests.py`. It runs against a temporary test database and never calls the real upstream API: the importer tests replace the network fetch with fake feeds, so the tests are fast, deterministic and work offline.
 
**Importer**
 
- Records are created, and running the import twice leaves one row per ID (idempotency).
- Re-importing a record whose upstream values changed refreshes the stored row.
- Whitespace is trimmed, city names are title-cased, and timestamps without a timezone are stored as UTC.
- Records with a missing field, a blank field, an unparseable date or a null ID are rejected, while valid records in the same feed still import.
- Duplicate IDs within one feed collapse to a single row (the last one wins).
- An empty feed is handled without error.
- An upstream connection failure or HTTP error status raises a clear `CommandError`, and existing data in the database is left untouched.

**Sightings endpoint**
 
- Default ordering (newest first) and pagination.
- Filters: city and species (case-insensitive), inclusive date ranges, and combinations of filters.
- Free-text search across city, species and Latin name, and reversing the sort order.
- A malformed date returns `400`, an unknown ID returns `404`, and write methods return `405`.
  
**Reports**
 
- Counts per city, per region and over time, checked against a small fixture with known totals.
- Weekly trends group by ISO week (starting Monday), monthly trends group by calendar month, and the interval defaults to monthly.
- Filters apply to every report, and an empty result returns an empty list.
- Cities missing from the region mapping appear under `"Unknown"`.
- An invalid `interval` returns `400`, and so does a malformed filter value on every report endpoint.
  
**Not covered**
 
The tests do not exercise the live upstream API, the Swagger/OpenAPI output, or behaviour under real network conditions such as slow responses. The retry-with-backoff configuration on the HTTP session is therefore not tested directly. The tests only verify how the importer reacts once a failure is raised.
 

## Limitations and future work

- **No scheduled refresh.** The import runs on demand. In production I would run it on a schedule (cron or Celery beat) and expose a `/api/status/` endpoint with the last import time and a comparison against `/data/stats`.
- **No authentication or rate limiting.** The API is read-only and the data is public, but a real deployment would add throttling.
- **Full-table updates on re-import.** Each run rewrites every row. At this size that is fine, but at scale I would compare fields first and only update rows that changed.
- **City-level granularity only.** The feed has no coordinates, so there is no map or distance-based querying. If coordinates were available, PostGIS would be the next step.
- **Containerisation.** A Dockerfile and `docker-compose.yml` with PostgreSQL would make the setup reproducible with one command.
- **Insights.** With more time I would add simple anomaly detection to the trends report, for example flagging periods that sit well above a city's rolling average.

## Author

Nicholas Hauptfleisch
