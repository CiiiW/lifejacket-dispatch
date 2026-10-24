#!/usr/bin/env bash
# Start the pinned GCP development simulator in its own working directory.
set -euo pipefail
sitl_root="${SITL_ROOT:-/home/jupyter/sitl-tools}"
mkdir -p "$sitl_root/run"
cd "$sitl_root/run"
exec "$sitl_root/prebuilt/arducopter" \
  --model quad --home 36.8,-121.801,0,0 --speedup 1 \
  --defaults "$sitl_root/ardupilot/Tools/autotest/default_params/copter.parm"
