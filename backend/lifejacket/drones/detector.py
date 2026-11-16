"""Read a published aerial detector and turn a frame into boxes.

The model perceives; it does not decide. `detect()` returns boxes with
confidences and nothing else -- no severity, no species, no recommendation.
What those boxes mean is assembled in code and reviewed by a person.

Three things this module is careful about:

**Weights are pinned and verified.** A Hugging Face repository is mutable:
the same repo id can serve different bytes tomorrow. `DetectorSource` takes a
revision (a commit SHA, not a branch name) and a SHA-256, and refuses to load
a file whose hash does not match. This is the same rule the photo collector
applies to source images.

**ONNX, not PyTorch.** The research environment needs torch and CUDA; the API
server does not. Loading an exported `.onnx` through `onnxruntime` keeps the
backend's install small and CPU-only. `onnxruntime` is NOT in
`backend/requirements.txt` -- it is an optional extra in
`backend/requirements-detector.txt`, imported lazily. The backend test suite
never touches it.

**There is a fake.** `FakeDetector` returns queued results with no model, no
download and no network, in the same shape as the real one, following
`llm/fake.py`. Tests and offline demos use it. It is what `load_detector()`
returns when the feature flag is off, which is the default.

    from lifejacket.drones.detector import load_detector

    detector = load_detector()           # FakeDetector unless configured
    for found in detector.detect(frame):
        print(found.label, found.confidence, found.box)
"""

from __future__ import annotations

import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image

logger = logging.getLogger(__name__)

# Order matters: it is the model output's class axis. This is
# DroneMegaDetector's order, read out of the published checkpoint's own
# `model_config` rather than copied from its README -- see
# `research/aerial_detector/dmd.py:describe_checkpoint`. Every fine-tune in
# that directory inherits it, so any checkpoint is a drop-in replacement for
# any other. A mismatch silently relabels every detection.
CLASS_NAMES = ("person", "animal", "vehicle")

_CHUNK = 1024 * 1024


class DetectorError(RuntimeError):
    """Weights could not be resolved, verified or loaded."""


@dataclass(frozen=True)
class Detection:
    """One box, in the coordinates of the original image."""

    label: str
    confidence: float
    box: tuple[int, int, int, int]  # x1, y1, x2, y2

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


class Detector(Protocol):
    def detect(self, image: Path) -> list[Detection]: ...


# --------------------------------------------------------------------------
# geometry, kept pure so it can be tested without onnxruntime
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Letterbox:
    """How an image of `source` size was fitted into a square `target` input."""

    scale: float
    pad_x: float
    pad_y: float
    target: int

    @classmethod
    def fit(cls, source: tuple[int, int], target: int) -> Letterbox:
        width, height = source
        if width <= 0 or height <= 0:
            raise DetectorError(f"image has a zero dimension: {source}")
        scale = min(target / width, target / height)
        new_width, new_height = round(width * scale), round(height * scale)
        return cls(scale, (target - new_width) / 2, (target - new_height) / 2, target)

    def to_source(self, x: float, y: float) -> tuple[float, float]:
        """Undo the fit: model-input pixels back to original-image pixels."""
        return (x - self.pad_x) / self.scale, (y - self.pad_y) / self.scale


def nms(boxes, scores, iou_threshold: float) -> list[int]:
    """Greedy non-maximum suppression. Returns kept indices, best first."""
    import numpy as np

    if len(boxes) == 0:
        return []
    boxes = np.asarray(boxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep: list[int] = []
    while order.size:
        best = order[0]
        keep.append(int(best))
        if order.size == 1:
            break
        rest = order[1:]
        ix1 = np.maximum(x1[best], x1[rest])
        iy1 = np.maximum(y1[best], y1[rest])
        ix2 = np.minimum(x2[best], x2[rest])
        iy2 = np.minimum(y2[best], y2[rest])
        inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
        union = areas[best] + areas[rest] - inter
        overlap = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
        order = rest[overlap <= iou_threshold]
    return keep


def decode(
    raw,
    letterbox: Letterbox,
    source: tuple[int, int],
    names: tuple[str, ...] = CLASS_NAMES,
    confidence: float = 0.25,
    iou: float = 0.45,
) -> list[Detection]:
    """Ultralytics ONNX output -> detections in original-image coordinates.

    The exported tensor is (1, 4 + num_classes, anchors): four box values in
    model-input pixels, then one score per class. Some exports transpose the
    last two axes, so the class axis is located rather than assumed.
    """
    import numpy as np

    array = np.asarray(raw, dtype=np.float32)
    if array.ndim == 3:
        array = array[0]
    if array.ndim != 2:
        raise DetectorError(f"unexpected model output shape {np.shape(raw)}")
    expected = 4 + len(names)
    if array.shape[0] == expected:
        array = array.T
    elif array.shape[1] != expected:
        raise DetectorError(
            f"model output {array.shape} matches neither "
            f"(4 + {len(names)} classes, anchors) nor its transpose. "
            "The checkpoint's class count probably differs from CLASS_NAMES."
        )

    class_scores = array[:, 4:]
    best_class = class_scores.argmax(axis=1)
    best_score = class_scores.max(axis=1)
    above = best_score >= confidence
    if not above.any():
        return []

    kept = array[above]
    best_class, best_score = best_class[above], best_score[above]

    # cx, cy, w, h in model-input pixels -> x1, y1, x2, y2 in source pixels.
    cx, cy, w, h = kept[:, 0], kept[:, 1], kept[:, 2], kept[:, 3]
    corners = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    source_width, source_height = source
    boxes = []
    for x1, y1, x2, y2 in corners:
        sx1, sy1 = letterbox.to_source(x1, y1)
        sx2, sy2 = letterbox.to_source(x2, y2)
        boxes.append(
            [
                max(0.0, min(sx1, source_width)),
                max(0.0, min(sy1, source_height)),
                max(0.0, min(sx2, source_width)),
                max(0.0, min(sy2, source_height)),
            ]
        )

    results: list[Detection] = []
    # Suppress per class: a person standing beside a car is two boxes, not one.
    for class_index in sorted(set(best_class.tolist())):
        mask = best_class == class_index
        indices = np.flatnonzero(mask)
        subset = [boxes[i] for i in indices]
        for position in nms(subset, best_score[mask], iou):
            original = int(indices[position])
            x1, y1, x2, y2 = boxes[original]
            if x2 - x1 < 1 or y2 - y1 < 1:
                continue
            label = names[class_index] if class_index < len(names) else str(class_index)
            results.append(
                Detection(
                    label=label,
                    confidence=round(float(best_score[original]), 4),
                    box=(round(x1), round(y1), round(x2), round(y2)),
                )
            )
    results.sort(key=lambda d: -d.confidence)
    return results


# --------------------------------------------------------------------------
# weights
# --------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DetectorSource:
    """Where the weights come from, and how we know they are the right ones."""

    repo: str
    revision: str
    filename: str = "model.onnx"
    sha256: str = ""

    def validate(self) -> None:
        if not self.repo:
            raise DetectorError("no Hugging Face repo configured (DRONE_DETECTOR_REPO)")
        if not self.revision:
            raise DetectorError(
                "no revision pinned (DRONE_DETECTOR_REVISION). A branch name is "
                "not a pin: use the commit SHA the publish step printed."
            )
        if len(self.revision) < 7 or self.revision in {"main", "master"}:
            raise DetectorError(
                f"revision {self.revision!r} is a moving target, not a commit SHA"
            )

    def fetch(self, cache_dir: Path) -> Path:
        """Download once into `cache_dir` and verify the hash every time."""
        self.validate()
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:  # pragma: no cover - optional extra
            raise DetectorError(
                "huggingface-hub is not installed. It is an optional extra: "
                "pip install -r backend/requirements-detector.txt"
            ) from exc

        cache_dir.mkdir(parents=True, exist_ok=True)
        path = Path(
            hf_hub_download(
                repo_id=self.repo,
                filename=self.filename,
                revision=self.revision,
                cache_dir=str(cache_dir),
            )
        )
        if self.sha256:
            actual = file_sha256(path)
            if actual != self.sha256.lower():
                raise DetectorError(
                    f"{self.repo}@{self.revision[:12]}/{self.filename} hashes to "
                    f"{actual[:16]}..., expected {self.sha256[:16]}.... Refusing to "
                    "load. Either the pin is wrong or the file is not what was published."
                )
        else:
            logger.warning(
                "loading %s with no sha256 pin; set DRONE_DETECTOR_SHA256",
                self.repo,
            )
        return path


# --------------------------------------------------------------------------
# detectors
# --------------------------------------------------------------------------


@dataclass
class FakeDetector:
    """Offline stand-in. Returns queued results, then empty lists.

    Queue per-call results in order, the way ScriptedLLMClient queues replies:

        detector = FakeDetector()
        detector.queue([Detection("animal", 0.91, (10, 10, 60, 48))])

    `calls` records every path it was asked about, so a test can assert which
    frames were examined without a model existing anywhere.
    """

    queued: deque[list[Detection]] = field(default_factory=deque)
    calls: list[Path] = field(default_factory=list)

    def queue(self, detections: list[Detection]) -> FakeDetector:
        self.queued.append(list(detections))
        return self

    def detect(self, image: Path) -> list[Detection]:
        self.calls.append(Path(image))
        if not self.queued:
            return []
        return list(self.queued.popleft())


class OnnxDetector:
    """The real one. Holds an onnxruntime session over the published weights."""

    def __init__(
        self,
        model_path: Path,
        *,
        names: tuple[str, ...] = CLASS_NAMES,
        imgsz: int = 960,
        confidence: float = 0.25,
        iou: float = 0.45,
    ) -> None:
        try:
            import onnxruntime
        except ImportError as exc:  # pragma: no cover - optional extra
            raise DetectorError(
                "onnxruntime is not installed. It is an optional extra, kept out "
                "of backend/requirements.txt so the API install stays small: "
                "pip install -r backend/requirements-detector.txt"
            ) from exc

        if not model_path.exists():
            raise DetectorError(f"no model at {model_path}")
        self.model_path = model_path
        self.names = names
        self.imgsz = imgsz
        self.confidence = confidence
        self.iou = iou
        self.session = onnxruntime.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name

    def _preprocess(self, image: Image.Image) -> tuple[object, Letterbox]:
        import numpy as np

        box = Letterbox.fit(image.size, self.imgsz)
        new_size = (round(image.width * box.scale), round(image.height * box.scale))
        resized = image.convert("RGB").resize(new_size, Image.BILINEAR)
        # 114 grey is the Ultralytics letterbox fill; matching it matters,
        # because the model saw that colour in the padding during training.
        canvas = Image.new("RGB", (self.imgsz, self.imgsz), (114, 114, 114))
        canvas.paste(resized, (round(box.pad_x), round(box.pad_y)))
        array = np.asarray(canvas, dtype=np.float32) / 255.0
        return array.transpose(2, 0, 1)[None, ...], box

    def detect(self, image: Path) -> list[Detection]:
        path = Path(image)
        with Image.open(path) as handle:
            source = handle.size
            tensor, box = self._preprocess(handle)
        raw = self.session.run(None, {self.input_name: tensor})[0]
        return decode(
            raw,
            box,
            source,
            names=self.names,
            confidence=self.confidence,
            iou=self.iou,
        )


def load_detector(settings=None) -> Detector:
    """A FakeDetector unless the flag is on and the weights verify.

    Defaults to the fake, like every other drone feature in this codebase.
    Turning it on is a deliberate act that needs a repo, a pinned revision and
    a hash in the environment.
    """
    if settings is None:
        from lifejacket.config import get_settings

        settings = get_settings()

    if not getattr(settings, "drone_detector_enabled", False):
        return FakeDetector()

    source = DetectorSource(
        repo=settings.drone_detector_repo,
        revision=settings.drone_detector_revision,
        filename=settings.drone_detector_file,
        sha256=settings.drone_detector_sha256,
    )
    model_path = source.fetch(Path(settings.drone_detector_cache_dir))
    logger.info(
        "loaded aerial detector %s@%s (%s)",
        source.repo,
        source.revision[:12],
        source.filename,
    )
    return OnnxDetector(
        model_path,
        imgsz=settings.drone_detector_imgsz,
        confidence=settings.drone_detector_confidence,
        iou=settings.drone_detector_iou,
    )


# --------------------------------------------------------------------------
# DETR-family decoding
# --------------------------------------------------------------------------
#
# RF-DETR -- which DroneMegaDetector is built on -- is a set-prediction
# model. It emits a fixed number of queries, each with one box and a score
# per class, and **needs no NMS**: duplicate suppression is learned, not
# applied afterwards. That makes this decode simpler than the anchor-grid one
# above, not harder.
#
# Boxes come out as normalised `cx cy w h` in [0, 1] of the model input. The
# input is a straight resize of the whole frame, so denormalising by the
# original width and height is correct and the aspect-ratio stretch cancels
# out. No letterbox arithmetic.
#
# NOT YET RUN AGAINST A REAL EXPORT. The shapes and the normalisation are
# what RF-DETR documents, and the logic is unit-tested against synthetic
# tensors, but the first real export is where a transposed axis or an
# unexpected letterbox would show up. Draw the first detections on a frame
# and look at them before trusting this.


def decode_detr(
    boxes,
    logits,
    source: tuple[int, int],
    names: tuple[str, ...] = CLASS_NAMES,
    confidence: float = 0.25,
    already_sigmoid: bool = False,
) -> list[Detection]:
    """RF-DETR output -> detections in original-image coordinates.

    `boxes` is (queries, 4) normalised cx cy w h; `logits` is
    (queries, classes). RF-DETR trains with focal loss, so scores are
    per-class **sigmoid**, not a softmax over classes -- pass
    `already_sigmoid=True` if the export bakes it in.
    """
    import numpy as np

    boxes = np.asarray(boxes, dtype=np.float32)
    logits = np.asarray(logits, dtype=np.float32)
    if boxes.ndim == 3:
        boxes = boxes[0]
    if logits.ndim == 3:
        logits = logits[0]
    if boxes.ndim != 2 or boxes.shape[1] != 4:
        raise DetectorError(f"expected boxes of shape (queries, 4), got {boxes.shape}")
    if logits.shape[0] != boxes.shape[0]:
        # Some exports transpose the class axis onto the queries axis.
        if logits.shape[1] == boxes.shape[0]:
            logits = logits.T
        else:
            raise DetectorError(
                f"boxes {boxes.shape} and logits {logits.shape} disagree on query count"
            )
    if logits.shape[1] != len(names):
        raise DetectorError(
            f"model predicts {logits.shape[1]} classes but CLASS_NAMES has "
            f"{len(names)}. The checkpoint's class count differs from this build."
        )

    scores = logits if already_sigmoid else 1.0 / (1.0 + np.exp(-logits))
    best_class = scores.argmax(axis=1)
    best_score = scores.max(axis=1)
    keep = best_score >= confidence
    if not keep.any():
        return []

    width, height = source
    cx, cy, w, h = (boxes[keep, i] for i in range(4))
    x1 = np.clip((cx - w / 2) * width, 0, width)
    y1 = np.clip((cy - h / 2) * height, 0, height)
    x2 = np.clip((cx + w / 2) * width, 0, width)
    y2 = np.clip((cy + h / 2) * height, 0, height)

    results = []
    for index in range(int(keep.sum())):
        if x2[index] - x1[index] < 1 or y2[index] - y1[index] < 1:
            continue
        class_index = int(best_class[keep][index])
        results.append(
            Detection(
                label=names[class_index] if class_index < len(names) else str(class_index),
                confidence=round(float(best_score[keep][index]), 4),
                box=(
                    round(float(x1[index])),
                    round(float(y1[index])),
                    round(float(x2[index])),
                    round(float(y2[index])),
                ),
            )
        )
    results.sort(key=lambda d: -d.confidence)
    return results
