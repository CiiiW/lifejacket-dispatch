# Run the drone demo on your own computer

Each teammate gets an independent local application and database. No GCP role,
Google login, model API key, private NOAA file, drone, or Raspberry Pi is needed
for the Drone Lab workflow.

Install Python 3.11+ and Docker with the Compose plugin (Docker Desktop includes
it), and start Docker. You need internet for the first image/dependency downloads
and the map's OpenStreetMap tiles. From your checkout:

```bash
git checkout charlotte
git pull --ff-only
python3 scripts/local_demo.py
```

On Windows, `py scripts/local_demo.py` is equivalent. Open
<http://127.0.0.1:8080> and select **Drone Lab**. The script builds the current
code, starts the frontend/API/PostgreSQL stack, and checks API health. It creates
a private, Git-ignored `deploy/local.env` with a random local database password.
Rerunning the command after a pull rebuilds changed code and preserves the
password, database and uploaded photos. A port already in use can be changed:

```bash
python3 scripts/local_demo.py --port 18082
```

The app will then use <http://127.0.0.1:18082>. The chosen port is remembered.
The Compose project is named `lifejacket-local`, independent of the Workbench
staging project.

## Try the workflow

1. Select **Normal wind**, then **Build survey plan**.
2. Inspect the dashed synthetic route, distance, duration and battery estimate.
3. Check **I reviewed this synthetic route**, then **Run mock flight**.
4. Watch the yellow simulated position and synthetic telemetry. The accelerated
   replay ends at the invented home point.
5. Select **low battery** or **link loss** and run again. The mock stops at the
   injected fault; it does not simulate return-to-home recovery.
6. Select **High wind** and rebuild. The planner blocks the run and explains why.

The current controls use one invented survey area near Monterey Bay; they do
not use a NOAA record or a real drone base. The mock exercises application
contracts and basic route checks. It does not demonstrate flight dynamics,
airspace compliance, wildlife clearance, camera coverage or aircraft endurance.
Plans and traces are held in the tab and responses, not saved to the database.

## Optional historical data

The synthetic drone demo works without the workbook. Historical report density
is a separate layer in **Triage**. If you have an authorized local copy of the
NOAA workbook, aggregate it into your own local database:

```bash
python3 scripts/local_demo.py --import-noaa /private/path/Zhang_CA_2006-2025.xlsx
```

On Windows, pass your normal Windows file path in quotes. The one-off import
mounts the workbook read-only and persists coarse counts and provenance, not
original rows, detailed locations or remarks. Do not commit the workbook.
See [historical data limits](historical_strandings.md).

## Stop and troubleshoot

```bash
python3 scripts/local_demo.py --stop
```

This stops the containers and preserves local data. For logs:

```bash
docker compose -p lifejacket-local --env-file deploy/local.env -f deploy/compose.staging.yaml logs --tail=100 api web
```

If Docker reports a port conflict, use `--port 18082`. If it reports that Docker
is unavailable, start Docker Desktop or the Docker daemon. On a new checkout
the incident list and historical layer can be empty; **Drone Lab** remains usable.

The existing AI intake and coordination model calls still require their own
Google application credentials. The drone demo does not call those models.
This launch path exposes only a loopback web port on your computer; it does not
configure public hosting or a shared team database.

Architecture and the next integration step: [drone architecture](drone_architecture.md).

## Historical context in Drone Lab

On `charlotte-drone-historical-context`, Drone Lab also displays the existing
NOAA heatmap after import. Select a thresholded cell from the list; its outline
and bounds appear. **Selection does not move home or generate a flight from the
cell center.** Enter a small survey rectangle inside the chosen cell and a nearby
simulated home in the six coordinate fields. Build, inspect, acknowledge review
and run the existing mock. Coordinate/cell/wind edits clear the current plan,
review and trace. Reload the page after re-importing a changed workbook.

The historical checksum and cell indices travel with the plan. The API rejects
missing/stale evidence, cells below the threshold, and surveys outside the cell;
all existing range/battery/wind/exclusion checks still apply. Real historical
counts are context only. Survey/home are simulation inputs and telemetry remains
synthetic. No incidents or assignments are created.

Without a workbook, choose **Use synthetic demo area** and follow the original
walkthrough. To reproduce backend checks without Docker or Google credentials:

```bash
python3 -m venv .venv
# macOS/Linux; on Windows use .venv\Scripts\activate
source .venv/bin/activate
pip install -r backend/requirements-staging.txt pytest
pytest backend/tests/test_drones.py backend/tests/test_drone_historical_context.py backend/tests/test_historical_strandings.py
```

These tests create synthetic aggregate fixtures in temporary SQLite databases;
they do not require or redistribute the NOAA workbook. Start the existing local
Docker launcher for the interactive console. See the complete source review and
remaining MVP work in [drone_simulation_review.md](drone_simulation_review.md).
