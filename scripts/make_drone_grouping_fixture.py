"""Generate a rectangle video and SCRIPTED candidates, never model evaluation."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from lifejacket.drones.video import VideoMetadata, digest, prepare_video, write_review
from PIL import Image, ImageDraw


def candidates(second):
    result = []
    if second != 2:
        x = 100 + 10 * second
        result.append(
            {
                "box": [200, x, 400, x + 200],
                "kind": "other",
                "description": "Blue rectangle: scripted candidate A, not an animal",
            }
        )
    if second in {3, 4}:
        result.append(
            {
                "box": [600, 650, 800, 850],
                "kind": "other",
                "description": "Orange rectangle: scripted candidate B, not an animal",
            }
        )
    return result


def make_fixture(output):
    if output.exists():
        raise ValueError("Output already exists; use a new path")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for second in range(6):
            image = Image.new("RGB", (640, 480), "#10182b")
            draw = ImageDraw.Draw(image)
            draw.text(
                (12, 12), f"SYNTHETIC RECTANGLES - NOT ANIMALS - {second}s", fill="white"
            )
            for candidate in candidates(second):
                y1, x1, y2, x2 = candidate["box"]
                draw.rectangle(
                    (x1 * 0.64, y1 * 0.48, x2 * 0.64, y2 * 0.48),
                    fill="dodgerblue" if " A," in candidate["description"] else "orange",
                )
            image.save(root / f"{second:04d}.png")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-framerate",
                "1",
                "-i",
                str(root / "%04d.png"),
                "-c:v",
                "mpeg4",
                "-threads",
                "1",
                str(root / "rectangles.mp4"),
            ],
            check=True,
        )
        manifest = prepare_video(
            root / "rectangles.mp4",
            output,
            VideoMetadata(
                evidence_kind="synthetic_test",
                source="Generated rectangles with scripted candidates; not animal footage",
                rights_note="Generated locally; no animal or model evidence",
            ),
            interval=1,
            max_frames=6,
        )
    results = {
        "manifest_sha256": digest(output / "manifest.json"),
        "stage": "scripted_fixture_not_model_output",
        "frames": [
            {
                "path": frame["path"],
                "status": "detected",
                "model": "scripted-fixture-not-ai",
                "animals": candidates(round(frame["offset_seconds"])),
            }
            for frame in manifest["frames"]
        ],
    }
    (output / "detections.json").write_text(json.dumps(results, indent=2) + "\n")
    write_review(output, manifest, results)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        make_fixture(args.output)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Fixture failed: {exc}\n")
    print(
        "Generated 6 synthetic frames with scripted boxes. "
        "No AI/model calls or animal evidence."
    )


if __name__ == "__main__":
    main()
