"""Bounded local video evidence preparation; never controls flight or creates cases."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MAX_BYTES = 1_000_000_000
MAX_DURATION = 600
MAX_PIXELS = 40_000_000
PTS = re.compile(r"\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:([\d.eE+\-]+)")


class VideoMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    evidence_kind: str = Field(pattern=r"^(toy_demo|wildlife_recording|synthetic_test)$")
    source: str = Field(min_length=1, max_length=500)
    rights_note: str = Field(min_length=1, max_length=1000)
    # Operator-supplied recording start, not import time or inferred MP4 creation time.
    recording_started_at: AwareDatetime | None = None


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ValueError("Install ffmpeg and ffprobe before preparing video") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Video processing exceeded its time limit") from exc
    if result.returncode:
        raise ValueError("Video could not be decoded; check format and file integrity")
    return result


def prepare_video(
    source: Path,
    output: Path,
    metadata: VideoMetadata,
    *,
    interval: float = 2,
    max_frames: int = 12,
) -> dict:
    """Copy original evidence, extract JPEGs with actual clip offsets, publish atomically.

    Restricted to local MOV/MP4/MKV files. The original is retained so hashes and
    sample offsets remain independently checkable. No network/media URLs accepted.
    """
    if not math.isfinite(interval) or not 0.5 <= interval <= 60:
        raise ValueError("Frame interval must be between 0.5 and 60 seconds")
    if (
        isinstance(max_frames, bool)
        or not isinstance(max_frames, int)
        or not 1 <= max_frames <= 60
    ):
        raise ValueError("Frame count must be between 1 and 60")
    formats = {".mov": "mov", ".mp4": "mov", ".mkv": "matroska"}
    source, output = source.resolve(), output.resolve()
    demuxer = formats.get(source.suffix.lower())
    if not source.is_file() or demuxer is None:
        raise ValueError("Choose an existing local MP4, MOV or MKV file")
    if not 0 < source.stat().st_size <= MAX_BYTES:
        raise ValueError("Video must be nonempty and at most 1 GB")
    if output.exists():
        raise ValueError("Output already exists; choose a new evidence directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".video-", dir=output.parent) as staging:
        root = Path(staging)
        original = root / ("source" + source.suffix.lower())
        shutil.copyfile(source, original)
        if original.stat().st_size > MAX_BYTES:
            raise ValueError("Video exceeds 1 GB")
        source_hash = digest(original)
        input_args = ["-protocol_whitelist", "file", "-f", demuxer, "-i", str(original)]
        probe = json.loads(
            _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    *input_args,
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                ],
                timeout=30,
            ).stdout
        )
        streams = [s for s in probe["streams"] if s.get("codec_type") == "video"]
        if not streams:
            raise ValueError("File has no video stream")
        stream = streams[0]
        width, height = int(stream["width"]), int(stream["height"])
        duration = float(probe["format"].get("duration", 0))
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
            raise ValueError("Video duration must be known and at most 10 minutes")
        if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= MAX_PIXELS):
            raise ValueError("Video dimensions exceed the supported decode limit")
        (root / "frames").mkdir()
        # Select by source presentation time, not an assumed constant frame rate.
        filters = (
            f"setpts=PTS-STARTPTS,select='isnan(prev_selected_t)+"
            f"gte(t-prev_selected_t,{interval})',"
            "scale=w='min(1280,iw)':h='min(1280,ih)':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2,showinfo"
        )
        result = _run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "info",
                "-threads",
                "1",
                *input_args,
                "-map",
                f"0:{stream['index']}",
                "-an",
                "-sn",
                "-dn",
                "-vf",
                filters,
                "-vsync",
                "vfr",
                "-frames:v",
                str(max_frames),
                "-threads",
                "1",
                "-q:v",
                "3",
                str(root / "frames" / "%04d.jpg"),
            ]
        )
        offsets = [float(value) for value in PTS.findall(result.stderr)]
        frames = sorted((root / "frames").glob("*.jpg"))
        if not frames or len(offsets) < len(frames):
            raise ValueError("Could not establish timestamps for extracted frames")
        records = []
        for frame, offset in zip(frames, offsets, strict=False):
            captured = (
                (metadata.recording_started_at + timedelta(seconds=offset)).isoformat()
                if metadata.recording_started_at
                else None
            )
            records.append(
                {
                    "path": frame.relative_to(root).as_posix(),
                    "sha256": digest(frame),
                    "offset_seconds": offset,
                    "captured_at": captured,
                    "aircraft_position": None,
                    "animal_position": None,
                }
            )
        manifest = {
            "schema_version": 1,
            "stage": "frames_prepared",
            "metadata": metadata.model_dump(mode="json"),
            "source": {
                "path": original.name,
                "sha256": source_hash,
                "bytes": original.stat().st_size,
                "duration_seconds": duration,
                "width": width,
                "height": height,
            },
            "extraction": {
                "interval_seconds": interval,
                "max_frames": max_frames,
                "max_edge": 1280,
                "timestamps": "relative_presentation_time",
                "ffmpeg_version": _run(["ffmpeg", "-version"]).stdout.splitlines()[0],
            },
            "sample_limit_reached": len(records) == max_frames,
            "frames": records,
            "limitations": [
                "Sparse frame sampling may miss animals; this is not video tracking.",
                "Toy recognition and aerial injury assessment are unvalidated.",
                "Capture times require a correct operator-supplied recording start.",
                "No GPS alignment, live stream, flight control or case creation.",
            ],
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        write_review(root, manifest)
        # A failed extraction leaves no partial evidence bundle at the requested path.
        root.rename(output)
    return manifest


def detect_frames(bundle: Path, *, client=None) -> dict:
    """Explicit opt-in to the existing detection agent; save every success/failure.

    No injury assessment, deduplication, target association or incident dispatch.
    """
    from lifejacket.agents.base import AgentError
    from lifejacket.agents.detection import DetectionAgent
    from lifejacket.llm.client import ImageInput

    manifest_path = bundle / "manifest.json"
    if (bundle / "detections.json").exists():
        raise ValueError("Detection results already exist; prepare a new bundle to rerun")
    manifest = json.loads(manifest_path.read_text())
    # Reject corrupted frames BEFORE spending any model calls.
    images = []
    for frame in manifest["frames"]:
        if not re.fullmatch(r"frames/\d{4}\.jpg", frame["path"]):
            raise ValueError("Invalid frame evidence path")
        path = bundle / frame["path"]
        if digest(path) != frame["sha256"]:
            raise ValueError("Frame integrity check failed")
        images.append(ImageInput(data=path.read_bytes(), photo_id=frame["path"]))
    if not 1 <= len(images) <= 60:
        raise ValueError("Invalid frame count")
    agent = DetectionAgent(client)
    results = {
        "manifest_sha256": digest(manifest_path),
        "stage": "detection_only",
        "frames": [],
    }
    for image in images:
        try:
            animals = agent.run(images=[image]).model_dump(mode="json")["animals"]
            row = {
                "path": image.photo_id,
                "status": "detected",
                "animals": animals,
                "metrics": agent.last_metrics,
                "model": agent.client.model,
            }
        except AgentError as exc:
            row = {"path": image.photo_id, "status": "failed", "error_kind": exc.kind}
        results["frames"].append(row)
        (bundle / "detections.json").write_text(json.dumps(results, indent=2) + "\n")
    write_review(bundle, manifest, results)
    return results


def write_review(root: Path, manifest: dict, results: dict | None = None) -> None:
    """Static local review works through file://; source notes are escaped."""
    statuses = {f["path"]: f for f in (results or {}).get("frames", [])}
    cards = []
    for frame in manifest["frames"]:
        status = statuses.get(frame["path"])
        label = "Not analyzed"
        if status:
            label = (
                f"{len(status['animals'])} candidate(s); human review needed"
                if status["status"] == "detected"
                else "Detection failed"
            )
        cards.append(
            f'<article><img src="{html.escape(frame["path"], quote=True)}" '
            'alt="Sampled frame">'
            f"<p>{frame['offset_seconds']:.3f}s · {html.escape(label)}</p>"
            f"<p>{html.escape(frame['captured_at'] or 'Capture time unknown')}</p></article>"
        )
    root.joinpath("review.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Drone video evidence review</title>'
        "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px;"
        "background:#f4f7fa;color:#142837}.grid{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(280px,1fr));gap:20px}article{background:white;padding:12px;"
        "border-radius:12px}img{width:100%}p{overflow-wrap:anywhere}</style>"
        "<h1>Drone video evidence review</h1><p>"
        + html.escape(
            manifest["metadata"]["evidence_kind"] + " · " + manifest["metadata"]["source"]
        )
        + "</p><p>Local evidence only. No rescue case created. Locations unknown. "
        "Sparse samples do not establish absence of animals or injury.</p>"
        + (
            "<p>Frame limit reached; this may not cover the entire clip.</p>"
            if manifest["sample_limit_reached"]
            else ""
        )
        + '<div class="grid">'
        + "".join(cards)
        + "</div>"
    )
