#!/usr/bin/env python3
"""Start the local web console, API and Postgres with Python's standard library only."""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "deploy/local.env"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, help="Local web port (default: saved port or 8080)"
    )
    parser.add_argument(
        "--stop", action="store_true", help="Stop containers and keep local data"
    )
    parser.add_argument(
        "--import-noaa", type=Path, help="Optional private workbook to aggregate locally"
    )
    args = parser.parse_args()
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    if args.import_noaa and not args.import_noaa.is_file():
        parser.error("the NOAA workbook was not found")
    if not shutil.which("docker"):
        parser.error("Install Docker with Compose, start Docker, then rerun this command")
    if subprocess.run(["docker", "info"], capture_output=True).returncode:
        parser.error("Docker is not running; start Docker and rerun this command")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        parser.error("Docker Compose v2 or newer is required")

    saved = {}
    if ENV_FILE.exists():
        saved = dict(
            line.split("=", 1)
            for line in ENV_FILE.read_text().splitlines()
            if line and not line.startswith("#")
        )
        if not re.fullmatch(r"[a-f0-9]{48}", saved.get("POSTGRES_PASSWORD", "")):
            parser.error(
                "deploy/local.env has an invalid password; "
                "preserve it and check the local setup"
            )
    elif args.stop:
        print("No local demo configuration exists yet.")
        return
    port = args.port if args.port is not None else int(saved.get("STAGING_PORT", "8080"))
    if not 1024 <= port <= 65535:
        parser.error("the saved local port is invalid")
    password = saved.get("POSTGRES_PASSWORD") or secrets.token_hex(24)
    # Keep the same database password between pulls/restarts; never reset volumes.
    with tempfile.NamedTemporaryFile(mode="w", dir=ENV_FILE.parent, delete=False) as target:
        target.write(f"POSTGRES_PASSWORD={password}\nSTAGING_PORT={port}\n")
        temporary = Path(target.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, ENV_FILE)
    compose = [
        "docker",
        "compose",
        "-p",
        "lifejacket-local",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(ROOT / "deploy/compose.staging.yaml"),
    ]
    if args.stop:
        subprocess.run([*compose, "stop"], cwd=ROOT, check=True)
        print("Stopped. Your local database and photos are preserved.")
        return
    print("Building the local demo. The first build downloads dependencies.", flush=True)
    subprocess.run(
        [*compose, "up", "--build", "-d", "--wait", "--wait-timeout", "180"],
        cwd=ROOT,
        check=True,
    )
    if args.import_noaa:
        subprocess.run(
            [
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "--volume",
                f"{args.import_noaa.resolve()}:/private/noaa.xlsx:ro",
                "api",
                "python",
                "-m",
                "lifejacket.services.historical_strandings",
                "/private/noaa.xlsx",
            ],
            cwd=ROOT,
            check=True,
        )
    url = f"http://127.0.0.1:{port}"
    for attempt in range(10):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=3) as response:
                if json.load(response) != {"status": "ok"}:
                    raise ValueError("Unexpected API health response")
            break
        except (urllib.error.URLError, TimeoutError):
            if attempt == 9:
                raise RuntimeError(
                    "The local API is not ready; inspect Docker Compose logs"
                ) from None
            time.sleep(0.5)
    print(f"\nOpen {url} and choose Drone Lab.")
    print("The mock drone demo needs no Google account, API key, or private NOAA workbook.")
    print("AI intake requires its separate model credentials. Data stays on this computer.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        print(f"Local demo could not start: {error}", file=sys.stderr)
        print("If the web port is occupied, rerun with --port 18080.", file=sys.stderr)
        sys.exit(1)
