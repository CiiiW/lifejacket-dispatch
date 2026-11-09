"""Choose a few useful evidence frames from a recorded drone video.

Three layers, cheapest first:

1. `scan_video`   local and free: decode densely at low resolution, drop blurred,
                  badly exposed and near-duplicate frames, cap the candidates.
2. observation    one model call per surviving candidate (agents/frame_observation.py)
                  describes what the frame shows. The model never picks frames.
3. `select_frames` deterministic: pick up to `max_frames` that differ in view and
                  side, are clear, and include any clearly shown notable detail.

Advisory evidence selection only. It does not identify species, diagnose injury,
track individuals, decide whether a drone should fly, or create cases.
"""

from __future__ import annotations

import json
import math
import shutil
import statistics
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from lifejacket.drones.video import (
    MAX_BYTES,
    MAX_DURATION,
    MAX_PIXELS,
    VideoMetadata,
    _run,
    digest,
)

SCAN_WIDTH, SCAN_HEIGHT = 160, 90
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)

LIMITATIONS = [
    "Advisory selection of evidence frames; not species identification or injury diagnosis.",
    "The model describes single frames only. Whether an animal is truly alone or hurt "
    "cannot be established from a few stills.",
    "Selection quality on drone footage is unvalidated.",
    "Frame times are relative to the start of the clip; no GPS or capture-time alignment.",
]


@dataclass
class ScanConfig:
    scan_fps: float = 2.0  # 0.5 s between inspected frames
    max_candidates: int = 40
    min_sharpness_ratio: float = 0.5  # of the clip's median sharpness
    min_brightness: float = 15.0
    max_brightness: float = 240.0
    dedupe_distance: int = 6  # Hamming bits out of 64 that make two frames "different"
    # A still view (hovering drone) must not collapse a long clip to one frame: keep a
    # frame at least this often even when it looks the same.
    max_gap_seconds: float = 8.0
    cut_difference: float = 40.0  # mean 0-255 pixel difference that marks a new shot


@dataclass
class Candidate:
    offset_seconds: float
    sharpness: float
    brightness: float
    shot: int
    hash: int


@dataclass
class SelectConfig:
    max_frames: int = 5
    min_clarity: int = 2
    new_view_bonus: float = 4.0
    new_side_bonus: float = 2.0
    new_shot_bonus: float = 1.5
    notable_bonus: float = 5.0
    too_close_seconds: float = 2.0
    too_close_penalty: float = 3.0
    min_gain: float = 2.0  # a further frame must add at least this much new information


# --- Layer 1: local scan ----------------------------------------------------


def _dhash(gray: Image.Image) -> int:
    small = gray.resize((9, 8), Image.BILINEAR)
    px = list(small.tobytes())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _thumb_difference(a: Image.Image, b: Image.Image) -> float:
    pa = list(a.resize((32, 18), Image.BILINEAR).tobytes())
    pb = list(b.resize((32, 18), Image.BILINEAR).tobytes())
    return sum(abs(x - y) for x, y in zip(pa, pb, strict=True)) / len(pa)


def probe_video(path: Path) -> dict:
    """Validate and describe a local video using the same limits as frame preparation."""
    formats = {".mov": "mov", ".mp4": "mov", ".mkv": "matroska"}
    demuxer = formats.get(path.suffix.lower())
    if not path.is_file() or demuxer is None:
        raise ValueError("Choose an existing local MP4, MOV or MKV file")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Video must be nonempty and at most 1 GB")
    out = _run(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-f", demuxer, "-i",
         str(path), "-show_streams", "-show_format", "-of", "json"],
        timeout=30,
    ).stdout
    probe = json.loads(out)
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
    return {
        "demuxer": demuxer,
        "stream_index": stream["index"],
        "width": width,
        "height": height,
        "duration_seconds": duration,
    }


def _decode_gray_frames(path: Path, info: dict, fps: float):
    """Yield (offset_seconds, 160x90 grayscale image) without writing frames to disk."""
    args = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
        "-protocol_whitelist", "file", "-f", info["demuxer"], "-i", str(path),
        "-map", f"0:{info['stream_index']}", "-an", "-sn", "-dn",
        "-vf", f"fps={fps},scale={SCAN_WIDTH}:{SCAN_HEIGHT},format=gray",
        "-f", "rawvideo", "-",
    ]
    size = SCAN_WIDTH * SCAN_HEIGHT
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        index = 0
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield index / fps, Image.frombytes("L", (SCAN_WIDTH, SCAN_HEIGHT), buf)
            index += 1
    finally:
        proc.stdout.close()
        proc.wait(timeout=30)
    if proc.returncode:
        raise ValueError("Video could not be decoded; check format and file integrity")


def choose_candidates(frames: list[Candidate], config: ScanConfig) -> list[Candidate]:
    """Drop blurred/badly exposed/near-duplicate frames, then cap by time spread."""
    if not frames:
        return []
    median_sharp = statistics.median(f.sharpness for f in frames)
    usable = [
        f
        for f in frames
        if config.min_brightness <= f.brightness <= config.max_brightness
        and f.sharpness >= config.min_sharpness_ratio * median_sharp
    ]
    kept: list[Candidate] = []
    for frame in usable:
        # Compare with the last kept frame of the same shot so a still scene collapses
        # to one frame but a new shot is always allowed through.
        previous = next((k for k in reversed(kept) if k.shot == frame.shot), None)
        if (
            previous is None
            or _hamming(previous.hash, frame.hash) >= config.dedupe_distance
            or frame.offset_seconds - previous.offset_seconds >= config.max_gap_seconds
        ):
            kept.append(frame)
    if len(kept) > config.max_candidates:
        # Keep the sharpest frame in each equal slice of the clip, so the whole
        # video stays covered instead of only its start.
        end = max(f.offset_seconds for f in kept) + 1e-6
        picked: dict[int, Candidate] = {}
        for frame in kept:
            slot = int(frame.offset_seconds / end * config.max_candidates)
            if slot not in picked or frame.sharpness > picked[slot].sharpness:
                picked[slot] = frame
        kept = [picked[s] for s in sorted(picked)]
    return kept


def scan_video(path: Path, info: dict, config: ScanConfig | None = None) -> dict:
    config = config or ScanConfig()
    frames: list[Candidate] = []
    previous_image = None
    shot = 0
    for offset, image in _decode_gray_frames(path, info, config.scan_fps):
        if previous_image is not None and (
            _thumb_difference(previous_image, image) > config.cut_difference
        ):
            shot += 1
        previous_image = image
        sharp = ImageStat.Stat(image.filter(_LAPLACIAN)).var[0]
        frames.append(
            Candidate(
                offset_seconds=round(offset, 3),
                sharpness=round(sharp, 2),
                brightness=round(ImageStat.Stat(image).mean[0], 1),
                shot=shot,
                hash=_dhash(image),
            )
        )
    candidates = choose_candidates(frames, config)
    return {"scanned": len(frames), "shots": shot + 1, "candidates": candidates}


# --- Layer 3: deterministic selection ---------------------------------------


def _quality(obs: dict, sharp_norm: float) -> float:
    return obs["clarity"] + obs["animal_size"] + 2 * sharp_norm


def select_frames(rows: list[dict], config: SelectConfig | None = None) -> list[dict]:
    """Pick frames from rows of {candidate: {...}, observation: {...}}.

    Greedy: the first frame is the best notable-and-clear one if any, else the
    highest quality. Each further frame must add a new view, side, notable detail
    or shot; otherwise fewer frames are returned rather than padding with repeats.
    """
    config = config or SelectConfig()
    usable = [
        r
        for r in rows
        if r.get("observation")
        and r["observation"]["animal_visible"]
        and r["observation"]["clarity"] >= config.min_clarity
    ]
    if not usable:
        return []
    top_sharp = max(r["candidate"]["sharpness"] for r in usable) or 1.0
    for r in usable:
        r["quality"] = _quality(r["observation"], r["candidate"]["sharpness"] / top_sharp)

    chosen: list[dict] = []
    seen_views: set[str] = set()
    seen_sides: set[str] = set()
    seen_shots: set[int] = set()
    notable_covered = False

    def gain(row: dict) -> tuple[float, float, list[str]]:
        obs, cand = row["observation"], row["candidate"]
        reasons, value = [], row["quality"]
        extra = 0.0
        if obs["view"] not in seen_views and obs["view"] != "other":
            extra += config.new_view_bonus
            reasons.append(f"new view: {obs['view'].replace('_', ' ')}")
        if obs["side"] not in seen_sides and obs["side"] != "unknown":
            extra += config.new_side_bonus
            reasons.append(f"new side: {obs['side'].replace('_', ' ')}")
        if obs["notable"] and obs["notable_clear"] and not notable_covered:
            extra += config.notable_bonus
            reasons.append("shows a notable detail clearly")
        if cand["shot"] not in seen_shots:
            extra += config.new_shot_bonus
            reasons.append("different shot")
        close = any(
            abs(c["candidate"]["offset_seconds"] - cand["offset_seconds"])
            < config.too_close_seconds
            for c in chosen
        )
        if close:
            value -= config.too_close_penalty
        return value + extra, extra, reasons

    while len(chosen) < config.max_frames:
        remaining = [r for r in usable if r not in chosen]
        if not remaining:
            break
        scored = [(gain(r), r) for r in remaining]
        (_, extra, reasons), best = max(scored, key=lambda s: s[0][0])
        # Beyond the first frame, stop when nothing adds enough new information.
        if chosen and extra < config.min_gain:
            break
        obs = best["observation"]
        best["selected_reason"] = (
            "; ".join(reasons) if reasons else "best clear view of the animal"
        )
        chosen.append(best)
        seen_views.add(obs["view"])
        seen_sides.add(obs["side"])
        seen_shots.add(best["candidate"]["shot"])
        if obs["notable"] and obs["notable_clear"]:
            notable_covered = True
    return sorted(chosen, key=lambda r: r["candidate"]["offset_seconds"])


# --- Orchestration ----------------------------------------------------------


def _extract_frame(source: Path, info: dict, offset: float, target: Path) -> None:
    _run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
            "-protocol_whitelist", "file", "-ss", f"{offset:.3f}", "-f", info["demuxer"],
            "-i", str(source), "-map", f"0:{info['stream_index']}", "-frames:v", "1",
            "-vf",
            "scale=w='min(1280,iw)':h='min(1280,ih)':"
            "force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-q:v", "3", str(target),
        ]
    )
    if not target.is_file():
        raise ValueError(f"Could not extract frame at {offset:.3f}s")


def _observe(image_path: Path, client, photo_id: str) -> dict:
    from lifejacket.agents.base import AgentError
    from lifejacket.agents.frame_observation import FrameObservationAgent
    from lifejacket.llm.client import ImageInput

    agent = FrameObservationAgent(client)
    try:
        image = ImageInput(data=image_path.read_bytes(), photo_id=photo_id)
        result = agent.run(images=[image])
    except AgentError as exc:
        return {"status": "failed", "error_kind": exc.kind}
    return {
        "status": "observed",
        "observation": result.model_dump(mode="json"),
        "metrics": agent.last_metrics,
        "model": agent.client.model,
    }


def select_from_video(
    source: Path,
    output: Path,
    metadata: VideoMetadata,
    *,
    client=None,
    scan: ScanConfig | None = None,
    selection: SelectConfig | None = None,
    workers: int = 4,
) -> dict:
    """Scan, describe candidates with the model, select, and publish an evidence bundle."""
    scan, selection = scan or ScanConfig(), selection or SelectConfig()
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Output already exists; choose a new evidence directory")
    info = probe_video(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".select-", dir=output.parent) as staging:
        root = Path(staging)
        original = root / ("source" + source.suffix.lower())
        shutil.copyfile(source, original)
        source_hash = digest(original)
        scanned = scan_video(original, info, scan)
        candidates: list[Candidate] = scanned["candidates"]
        if not candidates:
            raise ValueError("No usable frames found after local filtering")
        (root / "candidates").mkdir()
        paths = []
        for i, cand in enumerate(candidates):
            path = root / "candidates" / f"{i:04d}.jpg"
            _extract_frame(original, info, cand.offset_seconds, path)
            paths.append(path)

        # One agent per call: agents keep per-run state, so they are not shared.
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            results = list(
                pool.map(lambda p: _observe(p, client, p.relative_to(root).as_posix()), paths)
            )
        rows = []
        for cand, path, result in zip(candidates, paths, results, strict=True):
            record = asdict(cand)
            record["hash"] = f"{cand.hash:016x}"
            rows.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": digest(path),
                    "candidate": record,
                    "observation": result.get("observation"),
                    "status": result["status"],
                    "error_kind": result.get("error_kind"),
                    "metrics": result.get("metrics"),
                    "model": result.get("model"),
                }
            )
        if all(r["status"] == "failed" for r in rows):
            raise ValueError("Every model observation failed; no frames can be selected")

        chosen = select_frames(rows, selection)
        (root / "selected").mkdir()
        selected = []
        for n, row in enumerate(chosen, 1):
            target = root / "selected" / f"{n:02d}.jpg"
            shutil.copyfile(root / row["path"], target)
            selected.append(
                {
                    "path": target.relative_to(root).as_posix(),
                    "sha256": digest(target),
                    "offset_seconds": row["candidate"]["offset_seconds"],
                    "reason": row["selected_reason"],
                    "view": row["observation"]["view"],
                    "side": row["observation"]["side"],
                    "notable": row["observation"]["notable"],
                    "notable_clear": row["observation"]["notable_clear"],
                    "clarity": row["observation"]["clarity"],
                    "animal_size": row["observation"]["animal_size"],
                    "candidate_path": row["path"],
                }
            )
        for row in rows:
            row.pop("quality", None)
        manifest = {
            "schema_version": 1,
            "stage": "frames_selected",
            "metadata": metadata.model_dump(mode="json"),
            "source": {
                "path": original.name,
                "sha256": source_hash,
                "bytes": original.stat().st_size,
                **{k: info[k] for k in ("duration_seconds", "width", "height")},
            },
            "scan": {
                "config": asdict(scan),
                "frames_scanned": scanned["scanned"],
                "shots": scanned["shots"],
                "candidates": len(candidates),
                "ffmpeg_version": _run(["ffmpeg", "-version"]).stdout.splitlines()[0],
            },
            "selection": {"config": asdict(selection), "selected": selected},
            "candidates": rows,
            "limitations": LIMITATIONS,
        }
        (root / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (root / "review.html").write_text(render_selection_review(manifest))
        root.rename(output)
    return manifest


def render_selection_review(manifest: dict) -> str:
    """A static page listing the selected frames and why each was chosen."""
    from html import escape

    cards = []
    for item in manifest["selection"]["selected"]:
        notable = (
            f"<p><b>Notable:</b> {escape(item['notable'])}"
            f"{'' if item['notable_clear'] else ' (not clearly shown)'}</p>"
            if item["notable"]
            else ""
        )
        cards.append(
            f"<figure><img src='{escape(item['path'])}' width='480'>"
            f"<figcaption><b>{item['offset_seconds']:.1f}s</b> &middot; "
            f"{escape(item['view'].replace('_', ' '))}, "
            f"{escape(item['side'].replace('_', ' '))}"
            f" &middot; clarity {item['clarity']}/5, size {item['animal_size']}/5"
            f"<p>{escape(item['reason'])}</p>{notable}</figcaption></figure>"
        )
    limits = "".join(f"<li>{escape(text)}</li>" for text in manifest["limitations"])
    scan = manifest["scan"]
    return (
        "<!doctype html><meta charset='utf-8'><title>Selected frames</title>"
        "<style>body{font-family:sans-serif;margin:24px;max-width:1100px}"
        "figure{display:inline-block;vertical-align:top;margin:0 16px 24px 0;width:480px}"
        "</style>"
        f"<h1>Selected frames ({len(cards)})</h1>"
        f"<p>Scanned {scan['frames_scanned']} frames in {scan['shots']} shot(s); "
        f"{scan['candidates']} candidates described by the model.</p>"
        f"{''.join(cards) or '<p>No frame met the selection rules.</p>'}"
        f"<h2>Limits</h2><ul>{limits}</ul>"
    )
