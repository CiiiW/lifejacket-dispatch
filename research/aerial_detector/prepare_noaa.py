"""Turn NOAA drone video into a labelling-ready evaluation set.

    # from a bundle already made by scripts/drone_video.py prepare
    python prepare_noaa.py --bundle ~/aerial-data/noaa/bundle \
        --out ~/aerial-data/noaa_eval

    # or straight from a clip, which calls prepare_video for you
    python prepare_noaa.py --video NOAA_CLIP.mp4 --out ~/aerial-data/noaa_eval \
        --interval 5 --max-frames 50 \
        --source "NOAA Fisheries ..." --rights "NOAA Fisheries; ..."

Writes an `images/` directory and an empty-but-valid `_annotations.coco.json`
holding one entry per frame and the three DroneMegaDetector categories. Import
that into Label Studio or CVAT, draw the boxes, export COCO over the top, and
`evaluate.py` will read it.

Frames are spaced by `--interval` seconds on purpose. Fifty consecutive frames
would be fifty pictures of one moment; you would have labelled a single scene
fifty times and learned almost nothing.

Provenance travels with the data. The bundle manifest's source hash, rights
note and per-frame clip offsets are copied into the COCO `info` block and onto
each image record, so a frame can always be traced back to the second of video
it came from. A source being hosted by NOAA is not by itself a reuse licence.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dmd import DMD_CLASSES, write_coco  # noqa: E402

REPO_ROOT = HERE.parents[1]


def build_bundle(video: Path, work: Path, args) -> Path:
    """Call the repo's existing offline extractor. No cloud, no network."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from lifejacket.drones.video import VideoMetadata, prepare_video

    metadata = VideoMetadata(
        evidence_kind="wildlife_recording",
        source=args.source,
        rights_note=args.rights,
        recording_started_at=None,
    )
    bundle = work / "bundle"
    print(f"  extracting frames from {video}")
    prepare_video(
        video,
        bundle,
        metadata,
        interval=args.interval,
        max_frames=args.max_frames,
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--bundle", type=Path, help="a directory with manifest.json")
    source_group.add_argument("--video", type=Path, help="a local .mp4/.mov/.mkv")
    parser.add_argument("--out", type=Path, required=True, help="dataset directory to create")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between frames; 0.5-60 (default: 5)",
    )
    parser.add_argument(
        "--max-frames", type=int, default=50, help="1-60; 50 is a good eval set (default: 50)"
    )
    parser.add_argument("--source", default="NOAA aerial video", help="provenance string")
    parser.add_argument(
        "--rights",
        default="Rights unverified. Hosting by NOAA is not by itself a reuse licence.",
        help="rights note copied into the dataset",
    )
    parser.add_argument(
        "--copy", action="store_true", help="copy frames instead of symlinking"
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    out = args.out
    if out.exists() and not args.overwrite:
        parser.error(f"{out} already exists. Pass --overwrite or choose another path.")
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)

    bundle = args.bundle
    if args.video:
        try:
            bundle = build_bundle(args.video, out, args)
        except ValueError as exc:
            # drones/video.py raises ValueError when ffmpeg is absent.
            raise SystemExit(
                f"{exc}\n"
                "  conda install -y -c conda-forge ffmpeg\n"
                "  or: sudo apt-get install -y ffmpeg\n"
                "  Already installed but not visible? "
                "export AERIAL_FFMPEG_DIR=/path/to/bin and add it to PATH."
            ) from exc

    manifest_path = Path(bundle) / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(
            f"no manifest.json in {bundle}. Make one with:\n"
            "  PYTHONPATH=backend python scripts/drone_video.py prepare CLIP.mp4 "
            "--output BUNDLE --metadata META.json"
        )
    manifest = json.loads(manifest_path.read_text())

    images, annotations = [], []
    for index, frame in enumerate(manifest.get("frames", []), start=1):
        src = Path(bundle) / frame["path"]
        if not src.exists():
            print(f"  missing frame {src}, skipping")
            continue
        name = f"frame_{index:04d}{src.suffix.lower()}"
        dst = out / "images" / name
        if args.copy:
            shutil.copy2(src, dst)
        else:
            dst.symlink_to(src.resolve())
        with Image.open(src) as handle:
            width, height = handle.size
        images.append(
            {
                "id": index,
                "file_name": name,
                "width": width,
                "height": height,
                # Provenance, carried per frame so a box can always be traced
                # back to the second of video it came from.
                "offset_seconds": frame.get("offset_seconds"),
                "source_sha256": frame.get("sha256"),
            }
        )

    if not images:
        raise SystemExit(f"no usable frames found in {bundle}")

    coco_path = out / "_annotations.coco.json"
    write_coco(coco_path, images, annotations, DMD_CLASSES)

    # write_coco does not know about provenance; add it in place.
    doc = json.loads(coco_path.read_text())
    doc["info"] = {
        "description": "LifeJacket NOAA aerial evaluation set",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": manifest.get("metadata", {}).get("source", args.source),
        "rights_note": manifest.get("metadata", {}).get("rights_note", args.rights),
        "parent_video_sha256": manifest.get("source", {}).get("sha256"),
        "extraction": manifest.get("extraction", {}),
        "note": (
            "Annotations are empty by design. Label these frames, export COCO "
            "over this file, then run evaluate.py. Do not train on this set."
        ),
    }
    coco_path.write_text(json.dumps(doc, indent=2) + "\n")

    print(f"\n  {len(images)} frames -> {out / 'images'}")
    print(f"  skeleton -> {coco_path}")
    print(f"  source: {doc['info']['source']}")
    print(f"  rights: {doc['info']['rights_note']}")
    print(
        "\n  Next: label these frames locally (Label Studio or CVAT), using the\n"
        f"  three class names in order {list(DMD_CLASSES)}, export COCO over\n"
        "  _annotations.coco.json, then:\n"
        f"    python evaluate.py --weights dmd --data {coco_path} --tag noaa-dmd"
    )
    print(
        "\n  Label locally rather than on a hosted service: it keeps NOAA imagery\n"
        "  off third parties, which matters while the reuse question is open."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
