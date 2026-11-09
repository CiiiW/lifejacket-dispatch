"""Prepare recorded Mini 2/other video for local review; optional paid model detection."""

import argparse
from pathlib import Path

from lifejacket.drones.frame_select import (
    ScanConfig,
    SelectConfig,
    probe_video,
    scan_video,
    select_from_video,
)
from lifejacket.drones.video import (
    VideoMetadata,
    detect_frames,
    digest,
    prepare_video,
    write_review,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Offline extraction; no cloud calls")
    prepare.add_argument("video", type=Path)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--metadata", type=Path, required=True)
    prepare.add_argument("--interval", type=float, default=2)
    prepare.add_argument("--max-frames", type=int, default=12)
    detect = commands.add_parser(
        "detect", help="Uses existing Vertex credentials and model quota"
    )
    detect.add_argument("bundle", type=Path)
    select = commands.add_parser(
        "select",
        help="Pick a few useful frames from a whole video (model calls unless --scan-only)",
    )
    select.add_argument("video", type=Path)
    select.add_argument("--output", type=Path)
    select.add_argument("--metadata", type=Path)
    select.add_argument("--max-frames", type=int, default=5)
    select.add_argument("--scan-fps", type=float, default=2)
    select.add_argument("--max-candidates", type=int, default=40)
    select.add_argument("--workers", type=int, default=4)
    select.add_argument(
        "--scan-only",
        action="store_true",
        help="Local filtering only: print candidate times, no model calls, no files written",
    )
    review = commands.add_parser("review", help="Refresh overlays/worksheet; no model calls")
    review.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            metadata = VideoMetadata.model_validate_json(args.metadata.read_text())
            result = prepare_video(
                args.video,
                args.output,
                metadata,
                interval=args.interval,
                max_frames=args.max_frames,
            )
            print(
                f"Prepared {len(result['frames'])} frames. Open {args.output / 'review.html'}"
            )
        elif args.command == "select":
            scan = ScanConfig(scan_fps=args.scan_fps, max_candidates=args.max_candidates)
            if args.scan_only:
                found = scan_video(args.video, probe_video(args.video), scan)
                times = [c.offset_seconds for c in found["candidates"]]
                print(
                    f"Scanned {found['scanned']} frames, {found['shots']} shot(s); "
                    f"{len(times)} candidates would be sent to the model."
                )
                print("Offsets (s):", ", ".join(f"{t:g}" for t in times))
            else:
                if not args.output or not args.metadata:
                    raise ValueError("--output and --metadata are required unless --scan-only")
                metadata = VideoMetadata.model_validate_json(args.metadata.read_text())
                result = select_from_video(
                    args.video,
                    args.output,
                    metadata,
                    scan=scan,
                    selection=SelectConfig(max_frames=args.max_frames),
                    workers=args.workers,
                )
                chosen = result["selection"]["selected"]
                print(f"Selected {len(chosen)} frames. Open {args.output / 'review.html'}")
        elif args.command == "review":
            import json
            import re

            manifest = json.loads((args.bundle / "manifest.json").read_text())
            original = manifest["source"]["path"]
            if original not in {"source.mp4", "source.mov", "source.mkv"}:
                raise ValueError("Invalid original evidence path")
            if digest(args.bundle / original) != manifest["source"]["sha256"]:
                raise ValueError("Original video integrity check failed")
            for frame in manifest["frames"]:
                if not re.fullmatch(r"frames/\d{4}\.jpg", frame["path"]):
                    raise ValueError("Invalid frame evidence path")
                if digest(args.bundle / frame["path"]) != frame["sha256"]:
                    raise ValueError("Frame integrity check failed")
            result_path = args.bundle / "detections.json"
            results = json.loads(result_path.read_text()) if result_path.exists() else None
            write_review(args.bundle, manifest, results)
            print("Refreshed review page and worksheet. No model calls or evidence changes.")
        else:
            result = detect_frames(args.bundle)
            failed = sum(row["status"] == "failed" for row in result["frames"])
            print(
                f"Detection finished: {len(result['frames'])} frames, {failed} failed. "
                "No cases created."
            )
            if failed:
                raise SystemExit(1)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
