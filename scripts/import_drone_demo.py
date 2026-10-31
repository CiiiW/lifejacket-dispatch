"""Import prepared toy/synthetic frames into an opt-in local demo queue."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from lifejacket.drones.video import VideoMetadata, digest
from lifejacket.models.drone_demo import DemoFrameMetadata


def import_bundle(bundle: Path, api_url: str, *, client=None):
    parsed = urlparse(api_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Demo importer requires an HTTP loopback API URL")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    metadata = VideoMetadata.model_validate(manifest["metadata"])
    if metadata.evidence_kind not in {"toy_demo", "synthetic_test"}:
        raise ValueError("Wildlife recordings cannot be imported into the demo queue")
    if not 1 <= len(manifest["frames"]) <= 60:
        raise ValueError("Expected 1 to 60 frames")
    original_name = manifest["source"]["path"]
    if original_name not in {"source.mp4", "source.mov", "source.mkv"}:
        raise ValueError("Invalid original evidence path")
    if digest(bundle / original_name) != manifest["source"]["sha256"]:
        raise ValueError("Original video integrity check failed")
    detection_path = bundle / "detections.json"
    detections = {}
    if detection_path.exists():
        detected = json.loads(detection_path.read_text())
        if detected["manifest_sha256"] != digest(manifest_path):
            raise ValueError("Detection results refer to a different manifest")
        detections = {row["path"]: row for row in detected["frames"]}
    # Validate the entire batch before sending any image; uploads are per-frame,
    # idempotent so a network failure can be retried without discarding reviews.
    pending = []
    for frame in manifest["frames"]:
        if not re.fullmatch(r"frames/\d{4}\.jpg", frame["path"]):
            raise ValueError("Invalid frame path")
        path = bundle / frame["path"]
        if digest(path) != frame["sha256"]:
            raise ValueError("Frame integrity check failed")
        detection = detections.get(frame["path"])
        complete = detection and detection["status"] == "detected"
        body = DemoFrameMetadata(
            evidence_kind=metadata.evidence_kind,
            source=metadata.source,
            rights_note=metadata.rights_note,
            source_sha256=manifest["source"]["sha256"],
            frame_sha256=frame["sha256"],
            offset_seconds=frame["offset_seconds"],
            captured_at=frame["captured_at"],
            detection={"animals": detection["animals"]} if complete else None,
            detector_model=detection["model"] if complete else None,
            detection_status="completed" if complete else "failed" if detection else "not_run",
        )
        pending.append((path, body))
    owned = client is None
    connection = client or httpx.Client(timeout=30)
    results = []
    try:
        for path, body in pending:
            response = connection.post(
                api_url.rstrip("/") + "/drone-demo/frames",
                data={"metadata": body.model_dump_json()},
                files={"photo": (path.name, path.read_bytes(), "image/jpeg")},
            )
            response.raise_for_status()
            results.append(response.json()["demo_id"])
    finally:
        if owned:
            connection.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        rows = import_bundle(args.bundle, args.api_url)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        parser.exit(1, f"Demo import failed: {exc}. Retry after fixing the problem.\n")
    print(f"Imported {len(rows)} demo frames. No incidents or notifications created.")


if __name__ == "__main__":
    main()
