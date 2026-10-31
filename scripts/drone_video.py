"""Prepare recorded Mini 2/other video for local review; optional paid model detection."""

import argparse
from pathlib import Path

from lifejacket.drones.video import VideoMetadata, detect_frames, prepare_video


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
