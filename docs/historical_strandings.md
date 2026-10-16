# Historical California marine mammal reports

The responder map can display a historical **report-density** layer from the
NOAA California 2006–2025 workbook supplied to the project. It is separate
from current incidents. This is a feasibility visualisation for comparing
coastal areas; reporting effort, access, species mix, and estimated positions
vary over time. Cell colour is **not** the probability of a stranding, an
animal's present location, or an instruction to fly a drone.

## Local import

Keep the source workbook outside Git. The importer reads it in streaming mode
and stores only 0.1-degree cell counts and a SHA-256 checksum in the configured
database. It does not store source identifiers, names, addresses, remarks,
dates, species, or exact coordinates.

```bash
pip install -r backend/requirements.txt
DATABASE_URL=sqlite:////absolute/path/to/lifejacket.db \
  PYTHONPATH=backend python -m lifejacket.services.historical_strandings \
  /private/path/Zhang_CA_2006-2025.xlsx
```

Run this against the **same persistent database** used by the API. Re-running
replaces the old aggregate in one transaction. On a fresh API database the
map says data has not been imported yet. The source workbook is never fetched
by the client or checked in. A deployment with an ephemeral SQLite file will
lose the import on restart; use persistent database storage before deploying
this layer.

For a private persistent staging stack and an import command that mounts the
workbook read-only, see [staging setup](staging.md).

## Inclusion and public map behavior

- Include California records dated 2006–2025 with a confirmed confidence
  code, parseable decimal-degree coordinates, and coordinates inside a broad
  California bounding box (32–42.5° N, 125–114° W).
- Exclude missing or malformed coordinates, DMS-format fields, unconfirmed or
  unknown-confidence reports, and points outside the bounds. Report counts of
  each exclusion at import. The bounding box is a coarse sanity check, **not**
  a shoreline or state-boundary validation.
- `GET /historical-strandings/density` returns only cells containing at least
  10 reports over the entire period. Counts are bands (`10-24`, `25-99`,
  `100+`), with a cell center rather than any source position. No narrow
  date/species filters are offered because combinations could reveal sparse
  locations through subtraction.
- The web console renders a MapLibre heatmap; native clients render translucent
  circles. The toggle is disabled until the database has an import. Current
  incident pins remain separate and visible above the density layer.

## Next analysis before mission planning

Confirm NOAA's terms for publishing any derived map and the intended audience
for this dataset. Validate coastal/geographic placement, estimated-location
quality, reporting effort, species composition, and temporal drift with domain
experts before calling the display a risk model. Keep any future mission plan
behind coordinator approval and a simulator; this import supplies no flight
coordinates or permission to launch.
