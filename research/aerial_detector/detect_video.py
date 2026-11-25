"""Point a detector at a drone clip and see what it finds. No labels needed.

    # stock DroneMegaDetector on a Mini 2 clip
    python detect_video.py MY_CLIP.MP4 --out ~/aerial-data/runs/clip1

    # a fine-tune, sampled harder, only confident boxes
    python detect_video.py MY_CLIP.MP4 --out ~/aerial-data/runs/clip1-seals \
        --weights runs/seals-v1/checkpoint_best_total.pth --fps 4 --conf 0.4

Writes, into --out:

    frames/            the sampled JPEGs
    annotated/         the same frames with boxes drawn
    annotated.mp4      those stitched back into a video
    detections.json    every box, per frame, with its clip offset
    summary.json       counts a coordinator would care about

**This shows you what the model sees. It does not measure accuracy.**
Without labelled ground truth there is nothing to be right or wrong against,
so there is no precision or recall here and none is reported. For a real
score, label frames and use `evaluate.py`. This is for looking.

Use it to answer: does it find the animals at all, what confidence do they
come in at, what is it hallucinating on, and where does it lose them.

Frames are extracted straight with FFmpeg rather than through
`drones/video.py:prepare_video`, which caps at 60 frames because it builds
evidence bundles. This is a research tool; it samples a whole clip.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dmd import (  # noqa: E402
    DMD_CLASSES,
    Box,
    DmdError,
    draw_boxes,
    load_model,
    predict_images,
)

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".m4v", ".avi"}


def sha256_of(path: Path) -> str:
    """Streamed, rather than hashlib.file_digest, which needs Python 3.11."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


#: Places FFmpeg lands that a Jupyter kernel's PATH often misses. A kernel
#: inherits the Jupyter server's environment, not your login shell's, so
#: `sudo apt-get install ffmpeg` in a terminal can leave the notebook still
#: unable to find it. Set AERIAL_FFMPEG_DIR to add one.
_BINARY_SEARCH_DIRS = (
    "/opt/conda/bin",
    "/usr/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/snap/bin",
)


def resolve_binary(name: str) -> str | None:
    """Full path to `name`, looking beyond PATH before giving up."""
    found = shutil.which(name)
    if found:
        return found
    candidates = []
    override = os.environ.get("AERIAL_FFMPEG_DIR")
    if override:
        candidates.append(Path(override))
    candidates.append(Path(sys.prefix) / "bin")          # the active venv
    candidates.append(Path(sys.base_prefix) / "bin")     # the conda it came from
    candidates.extend(Path(d) for d in _BINARY_SEARCH_DIRS)
    for directory in candidates:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _missing_binary_message(name: str) -> str:
    searched = [os.environ.get("AERIAL_FFMPEG_DIR"), str(Path(sys.prefix) / "bin")]
    searched += list(_BINARY_SEARCH_DIRS)
    return (
        f"{name} not found.\n"
        "  Install it:\n"
        "    conda install -y -c conda-forge ffmpeg      # no sudo needed\n"
        "    sudo apt-get install -y ffmpeg              # Debian/Workbench\n"
        "    brew install ffmpeg                         # macOS\n"
        "  Already installed? Its directory is not visible to this kernel.\n"
        "  Point at it:  os.environ['AERIAL_FFMPEG_DIR'] = '/path/to/bin'\n"
        f"  PATH was: {os.environ.get('PATH', '')[:200]}\n"
        f"  Also searched: {', '.join(d for d in searched if d)}"
    )


def run_ffmpeg(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    resolved = resolve_binary(args[0])
    if resolved is None:
        raise DmdError(_missing_binary_message(args[0]))
    args = [resolved, *args[1:]]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DmdError(_missing_binary_message(args[0])) from exc
    except subprocess.TimeoutExpired as exc:
        raise DmdError(f"ffmpeg exceeded {timeout}s") from exc
    if result.returncode:
        tail = (result.stderr or "").strip().splitlines()[-3:]
        raise DmdError("ffmpeg failed:\n  " + "\n  ".join(tail))
    return result


def probe(video: Path) -> dict:
    result = run_ffmpeg(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(video),
        ],
        timeout=60,
    )
    doc = json.loads(result.stdout)
    stream = (doc.get("streams") or [{}])[0]
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "frame_rate": stream.get("avg_frame_rate"),
        "duration_seconds": float(doc.get("format", {}).get("duration") or 0),
    }


def extract(video: Path, frames_dir: Path, fps: float, max_edge: int) -> list[Path]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "ffmpeg", "-nostdin", "-y",
        "-i", str(video),
        "-vf", f"fps={fps},scale=w='min({max_edge},iw)':h='min({max_edge},ih)':"
               "force_original_aspect_ratio=decrease",
        "-fps_mode", "vfr",
        "-q:v", "2",
        str(frames_dir / "frame_%05d.jpg"),
    ])
    return sorted(frames_dir.glob("frame_*.jpg"))


def stitch(annotated_dir: Path, out: Path, fps: float) -> Path | None:
    if not sorted(annotated_dir.glob("frame_*.jpg")):
        return None
    run_ffmpeg([
        "ffmpeg", "-nostdin", "-y",
        "-framerate", str(fps),
        "-i", str(annotated_dir / "frame_%05d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        str(out),
    ])
    return out


def summarise(
    per_frame: dict[Path, list[Box]], fps: float, threshold: float
) -> dict:
    """The counts a coordinator would actually want, straight from the boxes.

    Descriptive only. "Three people were visible at once" is a count. It is
    not "a crowd is interfering", which is a judgement for a person.
    """
    peak: Counter[str] = Counter()
    frames_with: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    best: dict[str, float] = {}
    first_seen: dict[str, float] = {}

    for index, (_path, boxes) in enumerate(sorted(per_frame.items())):
        kept = [b for b in boxes if b.score >= threshold]
        counts = Counter(b.class_name for b in kept)
        offset = index / fps
        for name, count in counts.items():
            peak[name] = max(peak[name], count)
            frames_with[name] += 1
            totals[name] += count
            first_seen.setdefault(name, offset)
        for box in kept:
            best[box.class_name] = max(best.get(box.class_name, 0.0), box.score)

    frames = len(per_frame)
    return {
        "threshold": threshold,
        "frames": frames,
        "seconds_covered": round(frames / fps, 1) if fps else None,
        "peak_simultaneous": dict(peak),
        "frames_containing": dict(frames_with),
        "share_of_frames": {
            name: round(count / frames, 3) for name, count in frames_with.items()
        },
        "total_detections": dict(totals),
        "highest_confidence": {k: round(v, 3) for k, v in best.items()},
        "first_seen_seconds": {k: round(v, 1) for k, v in first_seen.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--weights", help="a .pth path. Omit for stock DroneMegaDetector"
    )
    parser.add_argument("--fps", type=float, default=2.0, help="frames sampled per second")
    parser.add_argument(
        "--conf",
        type=float,
        default=0.3,
        help="drawn and summarised at this; everything above --floor is in the JSON",
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=0.05,
        help="inference threshold, so you can re-threshold without re-running",
    )
    parser.add_argument("--max-edge", type=int, default=1280, help="downscale frames to this")
    parser.add_argument("--max-frames", type=int, help="stop after N frames")
    parser.add_argument("--no-video", action="store_true", help="skip annotated.mp4")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if not args.video.exists():
        raise SystemExit(f"no such file: {args.video}")
    if args.video.suffix.lower() not in VIDEO_SUFFIXES:
        raise SystemExit(f"{args.video.suffix} is not a video this reads {VIDEO_SUFFIXES}")
    if args.out.exists() and not args.overwrite:
        raise SystemExit(f"{args.out} exists. Pass --overwrite.")
    if args.conf < args.floor:
        parser.error(f"--conf {args.conf} is below --floor {args.floor}")

    args.out.mkdir(parents=True, exist_ok=True)
    info = probe(args.video)
    source_sha = sha256_of(args.video)
    print(f"  {args.video.name}")
    print(f"  {info['width']}x{info['height']}, {info['duration_seconds']:.1f}s, "
          f"{info['frame_rate']} fps")
    print(f"  sha256 {source_sha[:16]}...")

    print(f"\n  extracting at {args.fps} fps, max edge {args.max_edge}")
    frames = extract(args.video, args.out / "frames", args.fps, args.max_edge)
    if args.max_frames:
        frames = frames[: args.max_frames]
    if not frames:
        raise SystemExit("ffmpeg produced no frames")
    print(f"  {len(frames)} frames")

    model = load_model(args.weights)
    per_frame = predict_images(model, frames, threshold=args.floor)

    annotated_dir = args.out / "annotated"
    annotated_dir.mkdir(exist_ok=True)
    for path in frames:
        draw_boxes(path, per_frame[path], threshold=args.conf).save(
            annotated_dir / path.name, quality=90
        )

    video_path = None
    if not args.no_video:
        print("  stitching annotated.mp4")
        video_path = stitch(annotated_dir, args.out / "annotated.mp4", args.fps)

    detections = {
        path.name: {
            "offset_seconds": round(index / args.fps, 3),
            "boxes": [
                {
                    "class": b.class_name,
                    "score": round(b.score, 4),
                    "box": [round(b.x1), round(b.y1), round(b.x2), round(b.y2)],
                    "longest_side_px": round(b.longest_side),
                }
                for b in sorted(per_frame[path], key=lambda b: -b.score)
            ],
        }
        for index, path in enumerate(sorted(frames))
    }
    (args.out / "detections.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "video": str(args.video.resolve()),
                "video_sha256": source_sha,
                "video_info": info,
                "weights": args.weights or "DroneMegaDetector (stock)",
                "classes": list(DMD_CLASSES),
                "sample_fps": args.fps,
                "inference_floor": args.floor,
                "frames": detections,
            },
            indent=2,
        )
        + "\n"
    )

    summary = summarise(per_frame, args.fps, args.conf)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\n--- what it found at confidence {args.conf} ---")
    if not summary["peak_simultaneous"]:
        print("  nothing. Try lowering --conf; detections.json has everything")
        print(f"  above {args.floor}, so you can re-read it without re-running.")
    for name in DMD_CLASSES:
        if name not in summary["peak_simultaneous"]:
            continue
        print(
            f"  {name:8s} peak {summary['peak_simultaneous'][name]} at once, "
            f"in {summary['frames_containing'][name]}/{summary['frames']} frames "
            f"({summary['share_of_frames'][name]:.0%}), "
            f"best {summary['highest_confidence'][name]:.2f}, "
            f"first at {summary['first_seen_seconds'][name]:.0f}s"
        )

    sizes = [
        b.longest_side
        for boxes in per_frame.values()
        for b in boxes
        if b.score >= args.conf
    ]
    if sizes:
        sizes.sort()
        print(
            f"\n  box sizes: median {sizes[len(sizes) // 2]:.0f} px, "
            f"smallest {sizes[0]:.0f}, largest {sizes[-1]:.0f}"
        )
        if sizes[len(sizes) // 2] < 32:
            print("  Median under ~32 px: targets are near the detection floor.")
            print("  Fly lower or raise --max-edge before blaming the weights.")

    print(f"\n  {args.out / 'detections.json'}")
    print(f"  {args.out / 'summary.json'}")
    print(f"  {annotated_dir}")
    if video_path:
        print(f"  {video_path}")
    print(
        "\n  This is what the model SEES, not how accurate it is. There is no\n"
        "  ground truth here, so no precision or recall. To measure accuracy,\n"
        "  label frames and use evaluate.py."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
