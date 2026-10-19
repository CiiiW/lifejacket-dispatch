#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo 'Usage: deploy/import_historical.sh /absolute/path/to/Zhang_CA_2006-2025.xlsx' >&2
  exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source_path="$(cd -- "$(dirname -- "$1")" && pwd -P)/$(basename -- "$1")"

# The workbook is a read-only mount in this one-off process. It is not copied
# into either image, served by nginx, or stored in Postgres.
docker compose --env-file "$script_dir/staging.env" \
  -f "$script_dir/compose.staging.yaml" \
  run --rm --no-deps --volume "$source_path:/private/noaa.xlsx:ro" \
  api python -m lifejacket.services.historical_strandings /private/noaa.xlsx
