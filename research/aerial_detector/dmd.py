"""Shared DroneMegaDetector plumbing: weights, inference, COCO, scoring.

DroneMegaDetector is an RF-DETR Medium checkpoint trained as a three-class
aerial detector -- person, animal, vehicle -- on drone imagery flown at
roughly 50-120 m AGL, which is the Mini 2's operating range.

    https://github.com/ConservationDronesAI/DroneMegaDetector

Two facts about it shape everything downstream:

**Its class order is `person, animal, vehicle`.** Not the alphabetical or
intuitive order. Every fine-tune in this directory inherits it, and
`backend/lifejacket/drones/detector.py` matches it, so any checkpoint here is
a drop-in replacement for any other. Reordering silently relabels every
detection, which is why `publish.py` refuses a mismatch.

**Its `animal` class is effectively `mammal`.** The paper is titled "Detecting
Large Mammals"; the repo says behaviour on non-mammals is undefined, and the
abstract reports weaker transfer to unseen avian imagery. Seals are large
mammals and should be well within scope. Birds are the known gap, which is
what the bird fine-tune exists to close.

Nothing in this module imports torch or rfdetr at module level, so the scoring
and COCO helpers can be used -- and tested -- without a GPU environment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import struct
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

HERE = Path(__file__).parent
RESULTS = HERE / "results"

#: Class order is the interface. See the module docstring.
DMD_CLASSES: tuple[str, ...] = ("person", "animal", "vehicle")

DMD_RELEASE_URL = (
    "https://github.com/ConservationDronesAI/DroneMegaDetector/releases/"
    "download/v1.1/DroneMegaDetector_RFDETRMedium_2026.10.04.pth"
)
DMD_HF_REPO = "ConservationDrones/DroneMegaDetector"

#: SHA-256 of the v1.1 release checkpoint, verified by downloading it.
#: `ensure_dmd_weights` checks this and refuses a mismatch.
DMD_SHA256 = "a50d654c2c5b2739bf0874450a834bcc2a6190eb72eba31f926294e3d2f44c01"

#: Read out of the checkpoint's own `model_config`, not from documentation.
#: The class names in particular are worth knowing first-hand: the repo
#: README and the weights agree, but a published class order is the kind of
#: thing that gets transcribed wrong, and getting it wrong relabels silently.
DMD_NATIVE_RESOLUTION = 1280
DMD_PATCH_SIZE = 16
DMD_TRAINED_EPOCHS = 30
DMD_NUM_QUERIES = 300

#: Tile size DroneMegaDetector's batch script uses for large images, merging
#: overlapping detections with NMS. Separate from the model input resolution,
#: which happens to share the number.
DMD_TILE_SIZE = 1280
DMD_TILE_OVERLAP = 100

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


class DmdError(RuntimeError):
    """Weights, dataset or model could not be resolved."""


# --------------------------------------------------------------------------
# boxes and scoring -- pure, no torch
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    """One detection or one ground-truth box, in absolute image pixels."""

    x1: float
    y1: float
    x2: float
    y2: float
    class_id: int
    score: float = 1.0

    @property
    def class_name(self) -> str:
        return DMD_CLASSES[self.class_id] if self.class_id < len(DMD_CLASSES) else "?"

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    @property
    def longest_side(self) -> float:
        """Pixels on target -- the number that decides whether this is findable."""
        return max(self.x2 - self.x1, self.y2 - self.y1)

    @classmethod
    def from_xywh(cls, xywh, class_id: int, score: float = 1.0) -> Box:
        x, y, w, h = xywh
        x, y, w, h = float(x), float(y), float(w), float(h)
        return cls(x, y, x + w, y + h, class_id, score)

    def to_xywh(self) -> list[float]:
        return [self.x1, self.y1, self.x2 - self.x1, self.y2 - self.y1]


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def match_image(
    preds: list[Box], truth: list[Box], iou_threshold: float
) -> tuple[int, int, int]:
    """Greedy highest-confidence-first matching within one image.

    Returns (tp, fp, fn). A second box on an already-matched animal is a false
    positive, not a second hit -- otherwise a model that sprays boxes scores
    well.
    """
    unmatched = list(range(len(truth)))
    tp = 0
    for pred in sorted(preds, key=lambda p: -p.score):
        best_index, best_iou = None, iou_threshold
        for index in unmatched:
            overlap = iou(pred, truth[index])
            if overlap >= best_iou:
                best_index, best_iou = index, overlap
        if best_index is None:
            continue
        unmatched.remove(best_index)
        tp += 1
    return tp, len(preds) - tp, len(unmatched)


DEFAULT_SWEEP = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80)


def sweep(
    per_image: list[tuple[list[Box], list[Box]]],
    iou_threshold: float = 0.5,
    thresholds=DEFAULT_SWEEP,
) -> list[dict]:
    """Precision, recall and F1 across confidence thresholds.

    `blind_images` is the one to read first: frames that contain the target
    but produced no detection at all. That is the failure a coordinator would
    actually feel, and it is more honest than mAP about whether a model is
    usable.
    """
    rows = []
    for threshold in thresholds:
        tp = fp = fn = blind = 0
        for preds, truth in per_image:
            kept = [p for p in preds if p.score >= threshold]
            a, b, c = match_image(kept, truth, iou_threshold)
            tp, fp, fn = tp + a, fp + b, fn + c
            if truth and not kept:
                blind += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append(
            {
                "confidence": threshold,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "blind_images": blind,
            }
        )
    return rows


def best_row(rows: list[dict], key: str = "f1") -> dict:
    return max(rows, key=lambda r: r[key]) if rows else {}


def format_sweep(rows: list[dict]) -> str:
    lines = ["  conf    P       R       F1      TP     FP     FN     blind"]
    for row in rows:
        lines.append(
            f"  {row['confidence']:<6.2f} {row['precision']:<7.3f} {row['recall']:<7.3f} "
            f"{row['f1']:<7.3f} {row['tp']:<6d} {row['fp']:<6d} {row['fn']:<6d} "
            f"{row['blind_images']}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# COCO
# --------------------------------------------------------------------------


@dataclass
class CocoSet:
    """A parsed COCO annotation file, indexed the way evaluation needs it."""

    root: Path
    images: dict[int, dict] = field(default_factory=dict)
    boxes: dict[int, list[Box]] = field(default_factory=lambda: defaultdict(list))
    categories: dict[int, str] = field(default_factory=dict)

    def image_path(self, image_id: int) -> Path:
        return self.root / self.images[image_id]["file_name"]

    def __len__(self) -> int:
        return len(self.images)

    @property
    def box_count(self) -> int:
        return sum(len(v) for v in self.boxes.values())

    def per_class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for boxes in self.boxes.values():
            for box in boxes:
                counts[box.class_name] += 1
        return dict(sorted(counts.items()))


def load_coco(path: Path, classes: tuple[str, ...] = DMD_CLASSES) -> CocoSet:
    """Read a COCO file and map its categories onto the detector's class order.

    Category *names* are matched, not ids. A COCO export numbers categories
    however the labelling tool felt like, and trusting those numbers is how
    datasets end up silently relabelled.
    """
    doc = json.loads(Path(path).read_text())
    index = {name.lower(): i for i, name in enumerate(classes)}
    result = CocoSet(root=Path(path).parent)

    remap: dict[int, int] = {}
    for category in doc.get("categories", []):
        name = str(category["name"]).strip().lower()
        if name not in index:
            raise DmdError(
                f"{path}: category {category['name']!r} is not one of {list(classes)}. "
                "Rename it in the labelling export, or pass a matching `classes`."
            )
        remap[category["id"]] = index[name]
        result.categories[index[name]] = classes[index[name]]

    for image in doc.get("images", []):
        result.images[image["id"]] = image
    for ann in doc.get("annotations", []):
        if ann.get("iscrowd"):
            continue
        if ann["category_id"] not in remap:
            raise DmdError(f"{path}: annotation uses unknown category_id {ann['category_id']}")
        result.boxes[ann["image_id"]].append(
            Box.from_xywh(ann["bbox"], remap[ann["category_id"]])
        )
    return result


def write_coco(
    path: Path,
    images: list[dict],
    annotations: list[dict],
    classes: tuple[str, ...] = DMD_CLASSES,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "info": {"description": "LifeJacket aerial detector"},
                "images": images,
                "annotations": annotations,
                "categories": [
                    {"id": i, "name": name, "supercategory": "none"}
                    for i, name in enumerate(classes)
                ],
            },
            indent=2,
        )
        + "\n"
    )


# --------------------------------------------------------------------------
# weights and inference -- these do import torch, lazily
# --------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dmd_weights(cache_dir: Path | None = None, url: str = DMD_RELEASE_URL) -> Path:
    """Download the DroneMegaDetector checkpoint once, return its local path."""
    import requests

    cache_dir = Path(cache_dir or Path.home() / "aerial-data" / "weights")
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / url.rsplit("/", 1)[-1]
    if dest.exists():
        logger.info("using cached %s", dest)
        return dest

    print(f"  downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", end="", flush=True)
    print()
    digest = file_sha256(tmp)
    if url == DMD_RELEASE_URL and digest != DMD_SHA256:
        tmp.unlink(missing_ok=True)
        raise DmdError(
            f"downloaded weights hash to {digest[:16]}..., expected "
            f"{DMD_SHA256[:16]}.... Refusing to keep them. Either the release "
            "was republished or the download was corrupted."
        )
    tmp.rename(dest)
    print(f"  sha256 {digest}")
    return dest


def load_model(weights: Path | str | None = None, resolution: int | None = None):
    """An RF-DETR model. `weights=None` means stock DroneMegaDetector.

    Pass a fine-tune's `checkpoint_best_total.pth` to load that instead; the
    class order is unchanged, so everything downstream is identical.
    """
    from rfdetr import RFDETRMedium

    path = Path(weights) if weights else ensure_dmd_weights()
    if not Path(path).exists():
        raise DmdError(f"no checkpoint at {path}")
    kwargs = {"pretrain_weights": str(path)}
    if resolution:
        kwargs["resolution"] = resolution
    print(f"  loading {path}")
    return RFDETRMedium(**kwargs)


def to_boxes(detections, score_floor: float = 0.0) -> list[Box]:
    """A supervision `Detections` from rfdetr.predict -> our Box list."""
    out: list[Box] = []
    if detections is None or len(detections) == 0:
        return out
    for xyxy, confidence, class_id in zip(
        detections.xyxy, detections.confidence, detections.class_id, strict=True
    ):
        score = float(confidence)
        if score < score_floor:
            continue
        x1, y1, x2, y2 = (float(v) for v in xyxy)
        out.append(Box(x1, y1, x2, y2, int(class_id), score))
    return out


def predict_images(
    model,
    paths: list[Path],
    threshold: float = 0.05,
    progress_every: int = 25,
) -> dict[Path, list[Box]]:
    """Run the model over a list of images. Low threshold: sweep afterwards.

    Predict once at a permissive threshold and filter in `sweep()`, rather
    than re-running inference per threshold.
    """
    results: dict[Path, list[Box]] = {}
    for position, path in enumerate(paths, start=1):
        results[path] = to_boxes(model.predict(str(path), threshold=threshold))
        if progress_every and position % progress_every == 0:
            print(f"  ... {position}/{len(paths)}", flush=True)
    return results


def save_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")
    print(f"wrote {path}")
    return path


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Box):
        return asdict(value)
    raise TypeError(f"not JSON serialisable: {type(value)}")


def describe_checkpoint(path: Path | str) -> dict:
    """Read a checkpoint's own config: classes, resolution, patch size.

    Tries torch, then falls back to reading the pickle inside the .pth zip,
    so this works in a notebook without loading 135 MB of weights onto a GPU.
    Use it to confirm what a checkpoint actually is before trusting a README
    about it -- which is how the class order here was established.
    """
    import zipfile

    path = Path(path)
    try:
        import torch

        blob = torch.load(path, map_location="cpu", weights_only=False)
        config = blob.get("args", blob.get("model_config", {}))
        config = vars(config) if hasattr(config, "__dict__") else dict(config)
        return {
            "source": "torch",
            "num_classes": config.get("num_classes"),
            "class_names": config.get("class_names"),
            "resolution": config.get("resolution"),
            "patch_size": config.get("patch_size"),
            "epoch": blob.get("epoch"),
        }
    except Exception:  # torch absent, or an unexpected layout
        pass

    if not zipfile.is_zipfile(path):
        raise DmdError(f"{path} is not a torch zip checkpoint")
    archive = zipfile.ZipFile(path)
    name = next(n for n in archive.namelist() if n.endswith("data.pkl"))
    raw = archive.read(name)

    def int_after(key: bytes) -> int | None:
        for match in re.finditer(re.escape(key), raw):
            i = match.end()
            while i < len(raw) and raw[i] not in (0x4B, 0x4D, 0x4A) and i - match.end() <= 6:
                i += 1
            if i >= len(raw):
                continue
            if raw[i] == 0x4B:
                return raw[i + 1]
            if raw[i] == 0x4D:
                return struct.unpack("<H", raw[i + 1 : i + 3])[0]
            if raw[i] == 0x4A:
                return struct.unpack("<i", raw[i + 1 : i + 5])[0]
        return None

    names = _scan_string_list(raw, b"class_names")
    return {
        "source": "pickle-scan",
        "num_classes": int_after(b"num_classes"),
        "class_names": names or None,
        "resolution": int_after(b"resolution"),
        "patch_size": int_after(b"patch_size"),
        "epoch": int_after(b"epoch"),
    }


# Pickle opcodes we need to walk a list of strings out of a .pth without
# unpickling it (unpickling an untrusted checkpoint executes code).
_MARK, _EMPTY_LIST, _BINUNICODE = 0x28, 0x5D, 0x58
_BINPUT, _LONG_BINPUT, _APPENDS = 0x71, 0x72, 0x65


def _scan_string_list(raw: bytes, key: bytes) -> list[str] | None:
    """Read the list of strings stored under `key`, stopping at its APPENDS.

    A naive "find every string after the key" scan runs straight past the end
    of the list and into the next config entries, which is how this first
    reported `class_names` as sixteen items including `seed` and `sync_bn`.
    """
    match = re.search(re.escape(key), raw)
    if not match:
        return None
    i = match.end()
    limit = min(len(raw), i + 4096)
    while i < limit and raw[i] != _EMPTY_LIST:
        i += 1
    if i >= limit:
        return None
    i += 1
    if i < len(raw) and raw[i] in (_BINPUT, _LONG_BINPUT):
        i += 2 if raw[i] == _BINPUT else 5
    if i >= len(raw) or raw[i] != _MARK:
        return None
    i += 1

    out: list[str] = []
    while i < limit:
        op = raw[i]
        if op == _APPENDS:
            return out
        if op == _BINUNICODE:
            length = struct.unpack("<I", raw[i + 1 : i + 5])[0]
            if length > 256:
                return out or None
            out.append(raw[i + 5 : i + 5 + length].decode("utf-8", "replace"))
            i += 5 + length
        elif op == _BINPUT:
            i += 2
        elif op == _LONG_BINPUT:
            i += 5
        else:
            return out or None
    return out or None


# --------------------------------------------------------------------------
# looking at the output -- used by the notebooks
# --------------------------------------------------------------------------

#: Predictions in colour, ground truth always white, so the two never blur
#: together in a screenshot.
CLASS_COLOURS = {"person": "#4FC3F7", "animal": "#81C784", "vehicle": "#FFB74D"}
TRUTH_COLOUR = "#FFFFFF"


def draw_boxes(
    image_path: Path,
    predictions: list[Box] | None = None,
    truth: list[Box] | None = None,
    threshold: float = 0.0,
    width: int = 3,
):
    """Return a PIL image with predictions and ground truth drawn on it.

    Ground truth is a white dashed-looking outline; predictions are coloured
    by class and labelled with their score. Looking at twenty of these tells
    you more about a model than any single metric.
    """
    from PIL import Image, ImageDraw

    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    for box in truth or []:
        for offset in range(width):
            draw.rectangle(
                [box.x1 - offset, box.y1 - offset, box.x2 + offset, box.y2 + offset],
                outline=TRUTH_COLOUR,
            )

    for box in predictions or []:
        if box.score < threshold:
            continue
        colour = CLASS_COLOURS.get(box.class_name, "#E57373")
        draw.rectangle([box.x1, box.y1, box.x2, box.y2], outline=colour, width=width)
        label = f"{box.class_name} {box.score:.2f}"
        text_y = max(0.0, box.y1 - 14)
        draw.rectangle([box.x1, text_y, box.x1 + 8 * len(label), text_y + 13], fill=colour)
        draw.text((box.x1 + 2, text_y + 1), label, fill="#000000")
    return image


def show_grid(items, columns: int = 3, size: float = 5.0, titles=None):
    """Lay out PIL images in a grid. `items` is a list of images."""
    import matplotlib.pyplot as plt

    items = list(items)
    if not items:
        print("nothing to show")
        return None
    rows = (len(items) + columns - 1) // columns
    figure, axes = plt.subplots(
        rows, columns, figsize=(size * columns, size * rows * 0.62), squeeze=False
    )
    for index, axis in enumerate(axes.flat):
        axis.axis("off")
        if index < len(items):
            axis.imshow(items[index])
            if titles and index < len(titles):
                axis.set_title(titles[index], fontsize=9)
    figure.tight_layout()
    return figure


def plot_sweep(rows: list[dict], title: str = "", ax=None):
    """Precision, recall and F1 against confidence."""
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots(figsize=(7, 4))
    x = [r["confidence"] for r in rows]
    for metric, style in (("precision", "-o"), ("recall", "-s"), ("f1", "-^")):
        ax.plot(x, [r[metric] for r in rows], style, label=metric, markersize=4)
    best = best_row(rows)
    if best:
        ax.axvline(best["confidence"], color="#888", linestyle=":", linewidth=1)
        ax.annotate(
            f"best F1 {best['f1']:.2f}\n@ {best['confidence']:.2f}",
            (best["confidence"], best["f1"]),
            textcoords="offset points",
            xytext=(8, -18),
            fontsize=8,
        )
    ax.set_xlabel("confidence threshold")
    ax.set_ylabel("score")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title(title or "confidence sweep", fontsize=10)
    return ax


def pixels_on_target(boxes: list[Box]) -> list[float]:
    """Longest side of every box, in pixels.

    The single most useful diagnostic when a model finds nothing. A detector
    needs roughly 32 px to work with; if this histogram sits below that, no
    amount of fine-tuning fixes it and the answer is to fly lower or raise
    the input resolution.
    """
    return [b.longest_side for b in boxes]
