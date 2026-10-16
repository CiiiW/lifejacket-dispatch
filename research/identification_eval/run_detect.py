"""Does Gemini draw usable boxes around each animal in a photo?

    python run_detect.py                                  # the two default photos
    python run_detect.py photos/phoca_vitulina_04.jpg     # any images
    python run_detect.py --runs 3                         # more repeats, to see stability

Needs `gcloud auth application-default login`.

For each image, calls the model `--runs` times with prompts/identification/
detect_animals.md and writes into results_detect/:

    <image>__run<k>.jpg        the photo with numbered boxes drawn on it
    <image>__run<k>__<n>.jpg   the crop of each box (what identification would see)
    detect.jsonl               the raw reply for every run

The prompt is the only thing under test; no species is asked for. Judge by
eye: right number of animals, boxes tight, same answer across runs.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from lifejacket.agents.detection import DetectionAgent, crop_to_detection  # noqa: E402
from lifejacket.llm.client import ImageInput  # noqa: E402

DEFAULT_IMAGES = [
    HERE / "variants" / "pelecanus_occidentalis_02__rotate_2.jpg",
    HERE / "photos" / "phoca_vitulina_04.jpg",
]
OUT = HERE / "results_detect"


def to_pixels(box: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    """[ymin, xmin, ymax, xmax] on a 0-1000 scale -> (left, top, right, bottom) pixels."""
    ymin, xmin, ymax, xmax = box
    left, right = sorted((round(xmin / 1000 * width), round(xmax / 1000 * width)))
    top, bottom = sorted((round(ymin / 1000 * height), round(ymax / 1000 * height)))
    return left, top, right, bottom


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("images", nargs="*", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()

    images = [p if p.is_absolute() else HERE / p for p in args.images] or DEFAULT_IMAGES
    OUT.mkdir(exist_ok=True)
    agent = DetectionAgent()  # the same agent, prompt and crop the chatbot uses

    with (OUT / "detect.jsonl").open("a") as log:
        for path in images:
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            photo = ImageInput(data=path.read_bytes(), mime_type=mime)
            img = Image.open(path).convert("RGB")
            width, height = img.size
            for k in range(1, args.runs + 1):
                animals = agent.run(images=[photo]).animals
                latency = agent.last_metrics["detection_latency_seconds"]
                print(f"{path.name} run{k}: boxes={len(animals)} ({latency}s)")
                for n, a in enumerate(animals, 1):
                    print(f"   {n}. {a.kind:8} {a.box}  {a.description}")

                record = {"image": path.name, "run": k, **agent.last_response}
                log.write(json.dumps(record) + "\n")

                drawn = img.copy()
                draw = ImageDraw.Draw(drawn)
                for n, a in enumerate(animals, 1):
                    box = to_pixels(a.box, width, height)
                    draw.rectangle(box, outline="red", width=3)
                    draw.text((box[0] + 4, box[1] + 2), str(n), fill="yellow")
                    crop = crop_to_detection(photo, a)
                    (OUT / f"{path.stem}__run{k}__{n}.jpg").write_bytes(crop.data)
                drawn.save(OUT / f"{path.stem}__run{k}.jpg")


if __name__ == "__main__":
    main()
