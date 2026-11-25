"""Step 1: fold WAID, MMLA and VisDrone into one three-class YOLO dataset.

    # always do this first - dataset layouts vary between mirrors
    python harmonize.py --inspect --waid DIR --mmla DIR --visdrone DIR

    # then write the pooled set (symlinks, so it costs almost no disk)
    python harmonize.py --out data/pooled --waid DIR --mmla DIR --visdrone DIR

    # smoke test on a few hundred images before committing GPU hours
    python harmonize.py --out data/smoke --waid DIR --max-waid 200

Target classes are person, vehicle and animal. Source class names come from
each dataset's own metadata and are mapped through class_map.yaml; an unmapped
name stops the run rather than being dropped quietly.

Splits are never random. WAID and VisDrone keep their published splits. MMLA is
grouped by capture session and whole sessions are assigned by a hash of the
group name, so no two frames of the same animal can straddle train and test.

Writes <out>/dataset.yaml for Ultralytics, <out>/harmonize_report.json, and a
copy of the report in results/ for the record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PIL import Image

HERE = Path(__file__).parent
CLASS_MAP_PATH = HERE / "class_map.yaml"
RESULTS = HERE / "results"
SPLITS = ("train", "val", "test")

# VisDrone2019-DET annotation columns are
#   x, y, width, height, score, category, truncation, occlusion
# and this is the category index. 0 and 11 are meta-categories, not objects.
VISDRONE_CATEGORIES = [
    "ignored",
    "pedestrian",
    "people",
    "bicycle",
    "car",
    "van",
    "truck",
    "tricycle",
    "awning-tricycle",
    "bus",
    "motor",
    "others",
]

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


@dataclass
class Sample:
    """One image and its mapped boxes, ready to write."""

    source: str
    split: str
    image: Path
    group: str
    boxes: list[tuple[int, float, float, float, float]] = field(default_factory=list)


@dataclass
class Tally:
    """Everything the report needs to be honest about what happened."""

    images: Counter = field(default_factory=Counter)
    boxes: Counter = field(default_factory=Counter)
    per_class: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    dropped: Counter = field(default_factory=Counter)
    empty_images: Counter = field(default_factory=Counter)
    groups: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------


def to_yolo(
    x: float, y: float, w: float, h: float, iw: int, ih: int
) -> tuple[float, float, float, float] | None:
    """Absolute top-left xywh -> normalised cx cy w h, clipped to the image.

    Returns None for a box that is off-image or thinner than one pixel after
    clipping. Those are counted as drops, never written as zero-area labels.
    """
    if iw <= 0 or ih <= 0:
        return None
    x1, y1 = max(0.0, x), max(0.0, y)
    x2, y2 = min(float(iw), x + w), min(float(ih), y + h)
    if x2 - x1 <= 1.0 or y2 - y1 <= 1.0:
        return None
    return (
        ((x1 + x2) / 2) / iw,
        ((y1 + y2) / 2) / ih,
        (x2 - x1) / iw,
        (y2 - y1) / ih,
    )


def image_size(path: Path) -> tuple[int, int]:
    """Width and height without decoding the pixels."""
    with Image.open(path) as im:
        return im.size


def split_for_group(group: str, train: int = 70, val: int = 15) -> str:
    """Deterministic, content-free split assignment for a capture session.

    Hashing the group name means the same session always lands in the same
    split, on any machine, whatever order the files are walked in.
    """
    bucket = int(hashlib.md5(group.encode()).hexdigest()[:8], 16) % 100
    if bucket < train:
        return "train"
    if bucket < train + val:
        return "val"
    return "test"


def normalise_split(name: str) -> str | None:
    low = name.lower()
    if "train" in low:
        return "train"
    if "val" in low:  # covers 'val', 'valid', 'validation'
        return "val"
    if "test" in low:  # covers 'test', 'test-dev', 'testset'
        return "test"
    return None


# --------------------------------------------------------------------------
# class mapping
# --------------------------------------------------------------------------


class ClassMap:
    def __init__(self, path: Path) -> None:
        raw = yaml.safe_load(path.read_text())
        self.targets: list[str] = list(raw["targets"])
        self.index = {name: i for i, name in enumerate(self.targets)}
        self.datasets = raw["datasets"]

    def resolve(self, dataset: str, source_name: str) -> int | None:
        """Target index, or None if the class is explicitly ignored.

        Raises KeyError for a name that is in neither list. That is the point:
        a new species appearing in a dataset mirror should stop the run.
        """
        spec = self.datasets[dataset]
        key = source_name.strip().lower()
        mapping = {str(k).strip().lower(): v for k, v in (spec.get("map") or {}).items()}
        ignored = {str(k).strip().lower() for k in (spec.get("ignore") or [])}
        if key in mapping:
            return self.index[mapping[key]]
        if key in ignored:
            return None
        raise KeyError(
            f"{dataset}: class {source_name!r} is in neither `map` nor `ignore` "
            f"in {CLASS_MAP_PATH.name}. Add it deliberately."
        )


# --------------------------------------------------------------------------
# WAID
# --------------------------------------------------------------------------


def waid_layout(root: Path) -> dict[str, tuple[Path, Path]]:
    """Locate split directories under either published WAID layout."""
    found: dict[str, tuple[Path, Path]] = {}
    # Layout A: root/images/<split> + root/labels/<split>
    for split_dir in sorted((root / "images").glob("*")):
        split = normalise_split(split_dir.name) if split_dir.is_dir() else None
        labels = root / "labels" / split_dir.name
        if split and labels.is_dir():
            found[split] = (split_dir, labels)
    if found:
        return found
    # Layout B: root/<split>/images + root/<split>/labels
    for split_dir in sorted(p for p in root.glob("*") if p.is_dir()):
        split = normalise_split(split_dir.name)
        images, labels = split_dir / "images", split_dir / "labels"
        if split and images.is_dir() and labels.is_dir():
            found[split] = (images, labels)
    if found:
        return found
    # Layout C: the two layouts above, one level down (zip extracted into a dir)
    for child in sorted(p for p in root.glob("*") if p.is_dir()):
        nested = waid_layout(child)
        if nested:
            return nested
    return {}


def waid_names(root: Path) -> list[str]:
    for candidate in sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.yml")):
        try:
            doc = yaml.safe_load(candidate.read_text())
        except Exception:  # a stray unparseable yaml is not fatal
            continue
        if isinstance(doc, dict) and "names" in doc:
            names = doc["names"]
            if isinstance(names, dict):
                return [names[k] for k in sorted(names, key=int)]
            if isinstance(names, list):
                return list(names)
    raise SystemExit(
        f"WAID: no data.yaml with a `names:` list under {root}. "
        "Class indices cannot be mapped to names without it."
    )


def read_waid(root: Path, cmap: ClassMap, tally: Tally, limit: int | None):
    names = waid_names(root)
    tally.notes.append(f"waid class names from data.yaml: {names}")
    layout = waid_layout(root)
    if not layout:
        raise SystemExit(f"WAID: no images/labels split directories found under {root}")
    tally.notes.append(f"waid splits found: {sorted(layout)}")
    lookup = {i: cmap.resolve("waid", n) for i, n in enumerate(names)}

    seen = 0
    for split in SPLITS:
        if split not in layout:
            continue
        images_dir, labels_dir = layout[split]
        for image in sorted(images_dir.iterdir()):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if limit is not None and seen >= limit:
                return
            seen += 1
            label = labels_dir / f"{image.stem}.txt"
            boxes = []
            if label.exists():
                for line in label.read_text().splitlines():
                    parts = line.split()
                    if len(parts) < 5:
                        continue
                    source_index = int(float(parts[0]))
                    if source_index not in lookup:
                        raise SystemExit(
                            f"WAID: label {label} uses class index {source_index}, "
                            f"but data.yaml lists only {len(names)} names."
                        )
                    target = lookup[source_index]
                    if target is None:
                        tally.dropped["waid/ignored-class"] += 1
                        continue
                    cx, cy, w, h = (float(v) for v in parts[1:5])
                    if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0):
                        tally.dropped["waid/degenerate"] += 1
                        continue
                    boxes.append((target, cx, cy, w, h))
            yield Sample("waid", split, image, f"waid/{split}", boxes)


# --------------------------------------------------------------------------
# MMLA
# --------------------------------------------------------------------------


def find_coco_files(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*.json")):
        try:
            with path.open() as fh:
                head = fh.read(4096)
        except OSError:
            continue
        if '"images"' in head and ('"annotations"' in head or '"categories"' in head):
            out.append(path)
    return out


def mmla_group(rel: Path, regex: re.Pattern[str] | None) -> str:
    """Capture session for a frame, so whole sessions stay in one split."""
    if regex is not None:
        hit = regex.search(rel.name)
        if hit:
            return hit.group(1)
    parent = rel.parent
    parts = [p for p in parent.parts if p not in {".", "images", "frames", "data"}]
    if parts:
        return "/".join(parts)
    # Flat directory: strip a trailing frame number off the stem.
    return re.sub(r"[-_]?\d+$", "", rel.stem) or rel.stem


def read_mmla(
    root: Path,
    cmap: ClassMap,
    tally: Tally,
    limit: int | None,
    stride: int,
    group_regex: re.Pattern[str] | None,
):
    coco_files = find_coco_files(root)
    if not coco_files:
        raise SystemExit(f"MMLA: no COCO-shaped .json found under {root}")
    tally.notes.append(f"mmla coco files: {[str(p.relative_to(root)) for p in coco_files]}")

    # Fallback index so a file_name that does not resolve relative to the JSON
    # can still be found by basename.
    by_basename: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.suffix.lower() in IMAGE_SUFFIXES:
            by_basename.setdefault(path.name, path)

    buckets: dict[str, list[tuple[Path, list]]] = defaultdict(list)
    for coco_path in coco_files:
        doc = json.loads(coco_path.read_text())
        categories = {c["id"]: c["name"] for c in doc.get("categories", [])}
        lookup = {cid: cmap.resolve("mmla", name) for cid, name in categories.items()}
        tally.notes.append(
            f"mmla categories in {coco_path.name}: {sorted(categories.values())}"
        )

        anns: dict[int, list] = defaultdict(list)
        for ann in doc.get("annotations", []):
            anns[ann["image_id"]].append(ann)

        for entry in doc.get("images", []):
            file_name = entry["file_name"]
            candidates = [
                coco_path.parent / file_name,
                coco_path.parent / "images" / file_name,
                root / file_name,
                root / "images" / file_name,
            ]
            image = next((c for c in candidates if c.exists()), None)
            if image is None:
                image = by_basename.get(Path(file_name).name)
            if image is None:
                tally.dropped["mmla/image-not-on-disk"] += 1
                continue

            iw = int(entry.get("width") or 0)
            ih = int(entry.get("height") or 0)
            if iw <= 0 or ih <= 0:
                iw, ih = image_size(image)

            boxes = []
            for ann in anns.get(entry["id"], []):
                if ann.get("iscrowd"):
                    tally.dropped["mmla/iscrowd"] += 1
                    continue
                target = lookup.get(ann["category_id"], "missing")
                if target == "missing":
                    raise SystemExit(
                        f"MMLA: annotation uses category_id {ann['category_id']} "
                        f"which is absent from `categories` in {coco_path}"
                    )
                if target is None:
                    tally.dropped["mmla/ignored-class"] += 1
                    continue
                x, y, w, h = ann["bbox"]
                converted = to_yolo(x, y, w, h, iw, ih)
                if converted is None:
                    tally.dropped["mmla/degenerate"] += 1
                    continue
                boxes.append((target, *converted))

            rel = image.relative_to(root) if root in image.parents else Path(image.name)
            buckets[mmla_group(rel, group_regex)].append((image, boxes))

    tally.notes.append(f"mmla sessions: {len(buckets)}")
    sample_groups = sorted(buckets)[:5]
    tally.notes.append(f"mmla example session keys: {sample_groups}")

    seen = 0
    for group in sorted(buckets):
        frames = sorted(buckets[group], key=lambda pair: pair[0].name)
        split = split_for_group(group)
        for image, boxes in frames[::stride]:
            if limit is not None and seen >= limit:
                return
            seen += 1
            yield Sample("mmla", split, image, group, boxes)


# --------------------------------------------------------------------------
# VisDrone
# --------------------------------------------------------------------------


def visdrone_splits(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    candidates = [root, *(p for p in root.glob("*") if p.is_dir())]
    for path in candidates:
        if (path / "annotations").is_dir() and (path / "images").is_dir():
            split = normalise_split(path.name)
            if split:
                found[split] = path
    return found


def read_visdrone(root: Path, cmap: ClassMap, tally: Tally, limit: int | None):
    splits = visdrone_splits(root)
    if not splits:
        raise SystemExit(
            f"VisDrone: no <split>/images + <split>/annotations pair under {root}. "
            "Expected directories like VisDrone2019-DET-train."
        )
    tally.notes.append(f"visdrone splits found: {sorted(splits)}")
    lookup = {i: cmap.resolve("visdrone", n) for i, n in enumerate(VISDRONE_CATEGORIES)}

    seen = 0
    for split in SPLITS:
        if split not in splits:
            continue
        base = splits[split]
        for image in sorted((base / "images").iterdir()):
            if image.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if limit is not None and seen >= limit:
                return
            seen += 1
            iw, ih = image_size(image)
            ann_path = base / "annotations" / f"{image.stem}.txt"
            boxes = []
            if ann_path.exists():
                for line in ann_path.read_text().splitlines():
                    parts = [p for p in line.strip().split(",") if p != ""]
                    if len(parts) < 6:
                        continue
                    x, y, w, h = (float(v) for v in parts[:4])
                    category = int(parts[5])
                    if category not in lookup:
                        tally.dropped["visdrone/unknown-category"] += 1
                        continue
                    target = lookup[category]
                    if target is None:
                        tally.dropped["visdrone/ignored-class"] += 1
                        continue
                    converted = to_yolo(x, y, w, h, iw, ih)
                    if converted is None:
                        tally.dropped["visdrone/degenerate"] += 1
                        continue
                    boxes.append((target, *converted))
            yield Sample("visdrone", split, image, f"visdrone/{split}", boxes)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def link_or_copy(src: Path, dst: Path, copy: bool) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if copy:
        shutil.copy2(src, dst)
    else:
        os.symlink(src.resolve(), dst)


def pooled_stem(sample: Sample) -> str:
    """Filename carrying its provenance: source, capture session, frame.

    Worth the long names. When a validation image looks wrong you can see at a
    glance which dataset and which session it came from, without a lookup.
    """
    parts = [sample.source]
    if sample.group != f"{sample.source}/{sample.split}":
        slug = re.sub(r"[^A-Za-z0-9]+", "-", sample.group).strip("-")
        if slug:
            parts.append(slug)
    parts.append(sample.image.stem)
    return "__".join(parts)


def write_sample(sample: Sample, out: Path, cmap: ClassMap, tally: Tally, copy: bool) -> None:
    stem = pooled_stem(sample)
    images_dir = out / "images" / sample.split
    labels_dir = out / "labels" / sample.split
    image_dst = images_dir / f"{stem}{sample.image.suffix.lower()}"
    # Two datasets can share a stem; disambiguate with a short path hash.
    if image_dst.exists() or image_dst.is_symlink():
        digest = hashlib.md5(str(sample.image).encode()).hexdigest()[:6]
        stem = f"{stem}__{digest}"
        image_dst = images_dir / f"{stem}{sample.image.suffix.lower()}"
    link_or_copy(sample.image, image_dst, copy)

    lines = [
        f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for cls, cx, cy, w, h in sample.boxes
    ]
    (labels_dir / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))

    key = f"{sample.source}/{sample.split}"
    tally.images[key] += 1
    tally.boxes[key] += len(sample.boxes)
    tally.groups.add(sample.group)
    if not sample.boxes:
        tally.empty_images[key] += 1
    for cls, *_ in sample.boxes:
        tally.per_class[key][cmap.targets[cls]] += 1


def write_dataset_yaml(out: Path, cmap: ClassMap) -> Path:
    doc = {
        "path": str(out.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(cmap.targets)),
    }
    path = out / "dataset.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build_report(args, cmap: ClassMap, tally: Tally) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "targets": cmap.targets,
        "sources": {
            name: str(Path(value).resolve())
            for name, value in (
                ("waid", args.waid),
                ("mmla", args.mmla),
                ("visdrone", args.visdrone),
            )
            if value
        },
        "settings": {
            "mmla_stride": args.mmla_stride,
            "max_waid": args.max_waid,
            "max_mmla": args.max_mmla,
            "max_visdrone": args.max_visdrone,
            "copy": args.copy,
        },
        "images": dict(sorted(tally.images.items())),
        "boxes": dict(sorted(tally.boxes.items())),
        "boxes_per_class": {k: dict(v) for k, v in sorted(tally.per_class.items())},
        "images_with_no_boxes": dict(sorted(tally.empty_images.items())),
        "dropped_boxes": dict(sorted(tally.dropped.items())),
        "groups": len(tally.groups),
        "notes": tally.notes,
    }


def print_summary(report: dict) -> None:
    print("\n--- pooled dataset ---")
    totals: Counter = Counter()
    for key, count in report["images"].items():
        source, split = key.split("/")
        boxes = report["boxes"].get(key, 0)
        per_class = report["boxes_per_class"].get(key, {})
        shown = " ".join(f"{k}={v}" for k, v in sorted(per_class.items())) or "-"
        print(f"  {source:9s} {split:5s} {count:7d} images {boxes:8d} boxes   {shown}")
        totals[split] += count
    joined = "  ".join(f"{s}={totals[s]}" for s in SPLITS)
    print(f"\n  totals: {joined}")
    if report["dropped_boxes"]:
        print("\n  dropped boxes:")
        for reason, count in report["dropped_boxes"].items():
            print(f"    {reason:34s} {count}")
    empty = sum(report["images_with_no_boxes"].values())
    print(f"\n  images with no boxes (kept as background): {empty}")
    print(f"  capture groups: {report['groups']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--waid", type=Path, help="root of the extracted WAID dataset")
    parser.add_argument("--mmla", type=Path, help="root of the extracted MMLA dataset")
    parser.add_argument("--visdrone", type=Path, help="root holding VisDrone2019-DET-* dirs")
    parser.add_argument("--out", type=Path, help="where to write the pooled dataset")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="report what was found and stop, without writing anything",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="copy image files instead of symlinking them (slow, large)",
    )
    parser.add_argument(
        "--mmla-stride",
        type=int,
        default=10,
        help="keep every Nth frame per session; consecutive video frames are "
        "near-duplicates and inflate MMLA against the other sources (default: 10)",
    )
    parser.add_argument(
        "--mmla-group-regex",
        help="override session detection, e.g. '^(.*?)_frame' - group 1 is the key",
    )
    parser.add_argument("--max-waid", type=int)
    parser.add_argument("--max-mmla", type=int)
    parser.add_argument("--max-visdrone", type=int)
    parser.add_argument("--overwrite", action="store_true", help="replace an existing --out")
    args = parser.parse_args()

    if not any([args.waid, args.mmla, args.visdrone]):
        parser.error("give at least one of --waid, --mmla, --visdrone")
    if not args.inspect and not args.out:
        parser.error("--out is required unless --inspect is given")
    if args.mmla_stride < 1:
        parser.error("--mmla-stride must be at least 1")

    cmap = ClassMap(CLASS_MAP_PATH)
    tally = Tally()
    group_regex = re.compile(args.mmla_group_regex) if args.mmla_group_regex else None

    out = args.out
    if not args.inspect:
        if out.exists() and not args.overwrite:
            parser.error(f"{out} already exists. Pass --overwrite or choose another path.")
        if out.exists():
            shutil.rmtree(out)
        for split in SPLITS:
            (out / "images" / split).mkdir(parents=True, exist_ok=True)
            (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    streams = []
    if args.waid:
        streams.append(read_waid(args.waid, cmap, tally, args.max_waid))
    if args.mmla:
        streams.append(
            read_mmla(args.mmla, cmap, tally, args.max_mmla, args.mmla_stride, group_regex)
        )
    if args.visdrone:
        streams.append(read_visdrone(args.visdrone, cmap, tally, args.max_visdrone))

    written = 0
    for stream in streams:
        for sample in stream:
            if args.inspect:
                key = f"{sample.source}/{sample.split}"
                tally.images[key] += 1
                tally.boxes[key] += len(sample.boxes)
                tally.groups.add(sample.group)
                if not sample.boxes:
                    tally.empty_images[key] += 1
                for cls, *_ in sample.boxes:
                    tally.per_class[key][cmap.targets[cls]] += 1
            else:
                write_sample(sample, out, cmap, tally, args.copy)
            written += 1
            if written % 5000 == 0:
                print(f"  ... {written} images", flush=True)

    report = build_report(args, cmap, tally)
    report["mode"] = "inspect" if args.inspect else "write"
    print_summary(report)

    for note in report["notes"]:
        print(f"  note: {note}")

    if args.inspect:
        print("\n--inspect: nothing written. Check the splits and class names above,")
        print("then rerun with --out to build the pooled dataset.")
        return 0

    yaml_path = write_dataset_yaml(out, cmap)
    (out / "harmonize_report.json").write_text(json.dumps(report, indent=2) + "\n")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "harmonize_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nwrote {yaml_path}")
    print(f"wrote {out / 'harmonize_report.json'}")
    print(f"wrote {RESULTS / 'harmonize_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
