"""Make degraded copies of the test photos, to imitate what a reporter really sends.

    python make_variants.py               # 1 randomly chosen variant per photo
    python make_variants.py --per-photo 3
    python make_variants.py --all         # every degradation on every photo

Everything is deterministic: parameters are fixed and the only randomness
(which variants a photo gets, where an occluder sits) comes from a fixed seed,
so every run produces the same images and two prompt versions can be tested on
exactly the same inputs. Output goes to variants/, which is not committed.

Seven degradations, two strengths each (level 2 is the harsher one):

    blur         out of focus (hand shake, wrong focus)
    motion       the animal or the phone moved
    low_light    dusk, backlit, deep shadow
    far          the animal is small in the frame (taken from a distance)
    low_res      small, heavily compressed upload on a weak signal
    rotate       phone held sideways (90 degrees) or upside down (180)
    occlude      part of the animal hidden by a rock, kelp or a person's hand

"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

HERE = Path(__file__).parent
MANIFEST = HERE / "manifest.csv"
PHOTOS = HERE / "photos"
VARIANTS = HERE / "variants"
SEED = 20261005


def blur(img: Image.Image, level: int) -> Image.Image:
    radius = max(img.size) * (0.005, 0.012)[level - 1]
    return img.filter(ImageFilter.GaussianBlur(radius))


def motion(img: Image.Image, level: int) -> Image.Image:
    """Horizontal smear: average the image with shifted copies of itself."""
    length = max(3, int(max(img.size) * (0.02, 0.05)[level - 1]))
    pixels = np.asarray(img, dtype=np.float32)
    padded = np.pad(pixels, ((0, 0), (length, 0), (0, 0)), mode="edge")
    width = pixels.shape[1]
    total = sum(padded[:, shift:shift + width] for shift in range(length + 1))
    return Image.fromarray((total / (length + 1)).astype(np.uint8))


def low_light(img: Image.Image, level: int) -> Image.Image:
    brightness, contrast = ((0.45, 0.75), (0.22, 0.5))[level - 1]
    img = ImageEnhance.Brightness(img).enhance(brightness)
    return ImageEnhance.Contrast(img).enhance(contrast)


def far(img: Image.Image, level: int) -> Image.Image:
    """Shrink the photo and set it in the middle of a softly blurred copy of itself."""
    scale = (0.5, 0.22)[level - 1]
    width, height = img.size
    soft = ImageFilter.GaussianBlur(max(img.size) * 0.03)
    background = img.filter(soft)
    small_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    small = img.resize(small_size, Image.LANCZOS)
    background.paste(small, ((width - small.width) // 2, (height - small.height) // 2))
    return background


def low_res(img: Image.Image, level: int) -> Image.Image:
    """Small and heavily compressed. The JPEG quality is applied when saving."""
    long_edge = (256, 96)[level - 1]
    scale = long_edge / max(img.size)
    size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(size, Image.LANCZOS)


def rotate(img: Image.Image, level: int) -> Image.Image:
    return img.rotate((90, 180)[level - 1], expand=True)


def occlude(img: Image.Image, level: int, seed: str) -> Image.Image:
    """Cover part of the frame with a dark, earthy patch (rock, kelp, a hand)."""
    rng = random.Random(seed)
    fraction = (0.25, 0.45)[level - 1]
    width, height = img.size
    aspect = rng.uniform(0.6, 1.6)
    box_w = min(width, int((fraction * width * height * aspect) ** 0.5))
    box_h = min(height, int(fraction * width * height / max(box_w, 1)))
    left = rng.randint(0, width - box_w)
    top = rng.randint(0, height - box_h)
    base = np.array([62, 52, 42], dtype=np.float32)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, 18, (box_h, box_w, 3))
    patch = Image.fromarray(np.clip(base + noise, 0, 255).astype(np.uint8))
    out = img.copy()
    out.paste(patch.filter(ImageFilter.GaussianBlur(1.5)), (left, top))
    return out


DEGRADATIONS = {
    "blur": blur, "motion": motion, "low_light": low_light, "far": far,
    "low_res": low_res, "rotate": rotate, "occlude": occlude,
}
JPEG_QUALITY = {"low_res": (25, 10)}  # everything else saves at 90
COMBOS = [(kind, level) for kind in DEGRADATIONS for level in (1, 2)]


def apply(img: Image.Image, kind: str, level: int, seed: str) -> Image.Image:
    if kind == "occlude":
        return occlude(img, level, seed)
    return DEGRADATIONS[kind](img, level)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--per-photo", type=int, default=1, help="variants per photo")
    parser.add_argument("--all", action="store_true", help="every degradation on every photo")
    args = parser.parse_args()

    with open(MANIFEST, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if (PHOTOS / r["file"]).exists()]

    # Walk a shuffled list of combinations, handing each photo the next few, so
    # every degradation is used about equally often.
    order = COMBOS[:]
    random.Random(SEED).shuffle(order)
    cursor = 0

    VARIANTS.mkdir(exist_ok=True)
    index_rows = []
    for row in rows:
        if args.all:
            chosen = COMBOS
        else:
            count = min(args.per_photo, len(order))
            chosen = [order[(cursor + k) % len(order)] for k in range(count)]
            cursor += count

        original = Image.open(PHOTOS / row["file"]).convert("RGB")
        for kind, level in chosen:
            name = f"{row['case_id']}__{kind}_{level}.jpg"
            seed = f"{row['case_id']}|{kind}|{level}"
            quality = JPEG_QUALITY.get(kind, (90, 90))[level - 1]
            apply(original, kind, level, seed).save(VARIANTS / name, "JPEG", quality=quality)
            index_rows.append({
                "variant_file": name, "case_id": row["case_id"],
                "variant_type": kind, "level": level,
            })

    with open(VARIANTS / "variants.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["variant_file", "case_id", "variant_type", "level"]
        )
        writer.writeheader()
        writer.writerows(index_rows)
    print(f"{len(index_rows)} variants from {len(rows)} photos -> {VARIANTS}")


if __name__ == "__main__":
    main()
