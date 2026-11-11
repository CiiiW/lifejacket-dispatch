#!/usr/bin/env python3
"""Read-only prerequisites for the disposable drone stream rehearsal."""

import argparse
import importlib.util
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mediamtx", default="mediamtx")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    failures = []

    def report(name, ok, remedy=""):
        print(f"{'OK' if ok else 'MISSING'}: {name}" + (f" — {remedy}" if not ok else ""))
        if not ok:
            failures.append(name)

    for module in (
        "fastapi",
        "uvicorn",
        "pytest",
        "sqlalchemy",
        "pydantic_settings",
        "httpx",
        "PIL",
        "multipart",
        "google.genai",
    ):
        try:
            found = importlib.util.find_spec(module) is not None
        except ModuleNotFoundError:
            found = False
        report(
            module,
            found,
            "Install backend and development dependencies in this Python environment",
        )
    for name, command in (
        ("MediaMTX", args.mediamtx),
        ("FFmpeg", args.ffmpeg),
        ("FFprobe", "ffprobe"),
        ("Node.js", "node"),
    ):
        binary = shutil.which(command)
        valid = False
        if binary:
            try:
                result = subprocess.run(
                    [binary, "-version" if name in {"FFmpeg", "FFprobe"} else "--version"],
                    capture_output=True,
                    timeout=10,
                )
                valid = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        report(name, valid, "Install the official binary or pass its absolute path")
    for dependency in ("react", "react-dom"):
        report(
            f"console {dependency}",
            (ROOT / "clients/responder_console/node_modules" / dependency).is_dir(),
            "npm ci --prefix clients/responder_console",
        )
    report("esbuild", (ROOT / "node_modules/esbuild").is_dir(), "npm ci")
    report(
        "built coordinator rehearsal",
        (ROOT / "var/drone-stream-preview/app.js").is_file(),
        "node scripts/build_drone_stream_preview.mjs",
    )
    for port in (8935, 19350, 18554, 19997, 18941):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                free = True
            except OSError:
                free = False
        report(f"loopback port {port} available", free, "Stop the previous rehearsal/receiver")
    print("\nScope: generated video, disposable cases, fixture AI, no external notifications.")
    print("Not checked: phone/VPN reachability, DJI pairing, camera latency, real AI.")
    print("Video archive requires DRONE_RECORDINGS_ENABLED and persistent private storage.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
