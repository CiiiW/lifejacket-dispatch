#!/usr/bin/env python3
"""Publish a local recording into a rehearsal grant. Never controls an aircraft."""

import argparse
import ipaddress
import json
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--grant-file",
        type=Path,
        required=True,
        help="Private JSON file with publish_url; do not commit it",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    grant = json.loads(args.grant_file.read_text())
    if grant.get("source", {}).get("source_kind") != "sample_footage":
        parser.error("Use a recorded-demo session; do not label replay as a live flight")
    url = grant.get("publish_url", "")
    target = urlsplit(url)
    try:
        private = ipaddress.ip_address(target.hostname or "").is_private
    except ValueError:
        private = target.hostname == "localhost"
    if target.scheme not in {"rtmp", "rtmps"} or (target.scheme == "rtmp" and not private):
        parser.error("Use a private RTMP receiver or RTMPS")
    if not args.video.is_file() or args.video.stat().st_size > 1_000_000_000:
        parser.error("Choose a local recording under 1 GB")
    probe = subprocess.run(
        [
            args.ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(args.video.resolve()),
        ],
        capture_output=True,
        timeout=15,
    )
    if probe.returncode:
        parser.error("Unable to inspect the recording")
    info = json.loads(probe.stdout)
    duration = float(info.get("format", {}).get("duration", 0))
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if (
        not video
        or not 0 < duration <= 600
        or video.get("width", 0) * video.get("height", 0) > 20_000_000
    ):
        parser.error("Use a video of at most 10 minutes and 20 MP/frame")
    print("Publishing recorded rehearsal. No animal recognition or live flight is claimed.")
    try:
        result = subprocess.run(
            [
                args.ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-i",
                str(args.video.resolve()),
                "-t",
                "600",
                "-an",
                "-vf",
                "scale=1280:-2",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "veryfast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "30",
                "-f",
                "flv",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=630,
        )
    except subprocess.TimeoutExpired:
        parser.exit(1, "Rehearsal timed out; publishing stopped.\n")
    if result.returncode:
        parser.exit(
            1, "Rehearsal publishing stopped. Check the private receiver and session expiry.\n"
        )


if __name__ == "__main__":
    main()
