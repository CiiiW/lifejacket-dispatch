# Private staging for the current LifeJacket app

This Compose stack runs the **current FastAPI backend and Expo responder web
console** on one trusted Docker host. PostgreSQL and uploaded photos use named
volumes, so a container restart or `docker compose down` does not erase them.
The web port is bound to `127.0.0.1` on the host. Keep it that way: the API
still has writable incident and responder endpoints without authentication.
This is a private feasibility environment for trusted team members, not a
public service.

For a shared HTTPS URL with individual Google accounts, see the prepared
[team staging configuration](team_staging.md). Publishing it requires the
project administrator's IAM policy permissions.

## Start on a trusted host

Install Docker Engine with the Compose plugin on the host and check out the
`charlotte` branch. From the repository root:

```bash
cp deploy/staging.env.example deploy/staging.env
openssl rand -hex 24
# Put the generated value into POSTGRES_PASSWORD in deploy/staging.env.
docker compose --env-file deploy/staging.env -f deploy/compose.staging.yaml config --quiet
docker compose --env-file deploy/staging.env -f deploy/compose.staging.yaml up --build -d
```

`deploy/staging.env` is ignored by Git. Use a fresh, hex-only password; the
Compose file uses it in a PostgreSQL URL, and URL punctuation needs escaping.
The web build sets `EXPO_PUBLIC_API_URL=/api`, so both the map and API use one
origin behind nginx. A MapTiler key is optional and is public in the browser
bundle if set. Staging without one uses the project's existing OpenStreetMap
development tiles.

On a remote host, use an SSH tunnel rather than opening the port to the
internet:

```bash
ssh -L 8080:127.0.0.1:8080 user@your-staging-host
```

Then open `http://127.0.0.1:8080` in your browser. The console should load,
and `http://127.0.0.1:8080/api/health` should return `{"status":"ok"}`.
The responder list is empty until you seed or create incidents; the historical
layer is independent of live incidents.

## Import the NOAA workbook privately

Keep the workbook outside the repository on the staging host. After the stack
is running, import it through a read-only, one-off mount:

```bash
bash deploy/import_historical.sh /private/path/Zhang_CA_2006-2025.xlsx
curl http://127.0.0.1:8080/api/historical-strandings/density
```

The response should say `"available":true` and contain thresholded `cells`.
In the console, use **Show historical reports** and inspect the coloured
coastal areas. The workbook is not copied into an image or the database;
only 0.1-degree aggregate counts and a checksum persist. Re-running the import
replaces the aggregate atomically. See [data quality and map limits](historical_strandings.md).

## Operations and limits

- `docker compose ... down` preserves both named volumes. Do **not** add `-v`
  unless you intend to remove the database and photos.
- Back up the PostgreSQL volume before changing or replacing the staging host.
  This stack does not configure automated backups or schema migrations.
- The AI intake calls require Google application credentials and project
  access, which this private map staging does not configure. The density
  endpoint, responder map, and health check work without them.
- Do not open the loopback-bound port publicly. Before external sharing, add
  authentication, HTTPS, backups, migrations, and a reviewed data release
  policy. NOAA's requested acknowledgement applies to publications derived
  from the extract.
