"""Resumable image-only baseline and versioned provisional human review."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lifejacket.agents.base import AgentError
from lifejacket.agents.detection import DetectionAgent, crop_to_detection
from lifejacket.config import REPO_ROOT, settings
from lifejacket.llm.client import ImageInput, LLMClient
from lifejacket.models.schemas import AnimalDetection, AnimalGroup
from lifejacket.services.drone_vision import analyze_still

PILOT = REPO_ROOT / "research/public_condition_pilot/pilot_v1"
FLAGS = {
    "visible_wound": "wound",
    "bleeding": "bleeding",
    "entanglement": "entanglement",
    "swelling": "swelling",
    "abnormal_posture": "abnormal_posture",
    "emaciated": "emaciated",
}
UNSET = object()
Sign = Literal["observed", "not_visible", "uncertain"]


def now():
    return datetime.now(UTC).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


@contextmanager
def locked(path, *, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise Conflict("An analysis is already running for this image") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Conflict(ValueError):
    pass


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_prediction_id: str | None = None
    animal_number: int | None = Field(default=None, ge=1)
    manual_box: list[int] | None = None

    @field_validator("manual_box")
    @classmethod
    def box_valid(cls, value):
        if value is not None and (
            len(value) != 4
            or not all(0 <= v <= 1000 for v in value)
            or value[2] <= value[0]
            or value[3] <= value[1]
        ):
            raise ValueError("Use a nonempty [top, left, bottom, right] box on a 0–1000 scale")
        return value

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.animal_number is None) == (self.manual_box is None):
            raise ValueError("Choose a detected animal or draw one manual target")
        return self


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    expected_prediction_id: str | None = None
    reviewer: str = Field(min_length=1, max_length=80)
    qualification: str = Field(min_length=1, max_length=120)
    animal_present: Literal["yes", "no", "uncertain"]
    animal_group: AnimalGroup = AnimalGroup.UNKNOWN
    target_box: list[int] | None = None
    viewpoint: Literal["aerial", "ground", "underwater", "clinical_closeup", "unknown"]
    quality: Literal["clear", "limited", "unusable"]
    visible_wound: Sign = "uncertain"
    bleeding: Sign = "uncertain"
    entanglement: Sign = "uncertain"
    swelling: Sign = "uncertain"
    abnormal_posture: Sign = "uncertain"
    emaciated: Sign = "uncertain"
    predictions_exposed: bool = False
    source_exposed: bool = False
    notes: str = Field(default="", max_length=2000)

    @field_validator("target_box")
    @classmethod
    def valid_box(cls, value):
        return Target.box_valid(value)

    @model_validator(mode="after")
    def meaningful_target(self):
        if self.animal_present == "yes" and self.target_box is None:
            raise ValueError("Select or draw the animal you reviewed")
        if self.animal_present != "yes" and (
            self.target_box is not None or any(getattr(self, f) != "uncertain" for f in FLAGS)
        ):
            raise ValueError(
                "Without a confirmed animal, leave target and condition signs uncertain"
            )
        return self


class BaselineStore:
    def __init__(self, collection=PILOT, run_dir=None, *, scripted=False, client_factory=None):
        self.collection = Path(collection).resolve()
        self.run_dir = Path(
            run_dir or REPO_ROOT / "var/condition-baseline/public-pilot-live"
        ).resolve()
        if self.run_dir.is_relative_to(self.collection):
            raise ValueError("Keep predictions/reviews outside the immutable collection")
        manifest = self.collection / "candidates.jsonl"
        self.rows = {}
        for line in manifest.read_text().splitlines():
            row = json.loads(line)
            key = row["case_id"]
            if not re.fullmatch(r"inat_\d+_\d+", key) or key in self.rows:
                raise ValueError("Invalid or duplicate public case ID")
            self.rows[key] = row
        self.client_factory = client_factory or LLMClient
        self.mode = "scripted" if scripted else "live"
        files = [
            *list((REPO_ROOT / "prompts").glob("**/*.md")),
            *list((REPO_ROOT / "backend/lifejacket/agents").glob("*.py")),
            REPO_ROOT / "backend/lifejacket/services/drone_vision.py",
            REPO_ROOT / "backend/lifejacket/dispatch/severity.py",
            REPO_ROOT / "backend/lifejacket/taxonomy.py",
            REPO_ROOT / "backend/lifejacket/models/schemas.py",
            REPO_ROOT / "backend/lifejacket/llm/client.py",
            REPO_ROOT / "backend/lifejacket/llm/prompts.py",
            REPO_ROOT / "config/scoring.json",
            Path(__file__),
        ]
        fingerprint = {
            "manifest_sha256": digest(manifest.read_bytes()),
            "mode": self.mode,
            "model": "scripted-offline" if scripted else settings.llm_model,
            "source_sha256": {
                str(p.relative_to(REPO_ROOT)): digest(p.read_bytes()) for p in sorted(files)
            },
            "settings": {
                "identification_threshold": settings.identification_confidence_threshold,
                "max_output_tokens": settings.llm_max_output_tokens,
                "thinking_budget": settings.llm_thinking_budget,
                "max_retries": settings.llm_max_retries,
                "gcp_project": settings.gcp_project,
                "gcp_location": settings.gcp_location,
                "temperatures": {"detection": 0.1, "identification": 0.1, "assessment": 0.2},
            },
            "input_policy": (
                "Selected image pixels only; no species, condition text, "
                "group hints or location. EXIF removed; orientation normalized to JPEG95."
            ),
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with locked(self.run_dir / ".metadata.lock"):
            path = self.run_dir / "run.json"
            if path.exists():
                self.meta = json.loads(path.read_text())
                if self.meta["fingerprint"] != fingerprint:
                    raise Conflict(
                        "Inputs, prompts, code, model or settings changed; "
                        "start a new run directory"
                    )
            else:
                self.meta = {
                    "run_id": uuid.uuid4().hex,
                    "created_at": now(),
                    "fingerprint": fingerprint,
                    "case_count": len(self.rows),
                    "expert_labels_available": False,
                }
                atomic_json(path, self.meta)

    def row(self, key):
        if key not in self.rows:
            raise LookupError("Public research case not found")
        return self.rows[key]

    def image_path(self, key):
        row = self.row(key)
        path = (self.collection / row["photo"]["file"]).resolve()
        if not path.is_relative_to(self.collection / "photos"):
            raise ValueError("Photo path is outside collection photos")
        if not path.is_file():
            raise LookupError("Original photo unavailable; restore collection photos")
        if digest(path.read_bytes()) != row["photo"]["sha256"]:
            raise ValueError("Photo no longer matches the collection snapshot")
        return path

    def prediction(self, key):
        self.row(key)
        path = self.run_dir / "predictions" / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def review(self, key):
        self.row(key)
        path = self.run_dir / "reviews" / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def case(self, key):
        return {
            "source": self.row(key),
            "prediction": self.prediction(key),
            "review": self.review(key),
        }

    @staticmethod
    def check_prediction(current, expected):
        if (current or {}).get("prediction_id") != expected:
            raise Conflict("Model result changed; refresh this image before saving")

    def analyze(self, key, target=None, *, resume=False, expected_prediction_id=UNSET):
        row = self.row(key)
        with locked(self.run_dir / "locks" / f"{key}.lock", blocking=False):
            previous = self.prediction(key)
            if expected_prediction_id is not UNSET:
                self.check_prediction(previous, expected_prediction_id)
            if resume and previous and previous["status"] != "failed":
                return previous
            if target:
                self.check_prediction(previous, target.expected_prediction_id)
                if not previous:
                    raise Conflict("Run initial detection before selecting a target")
            started = time.monotonic()
            result = {
                "case_id": key,
                "prediction_id": uuid.uuid4().hex,
                "run_id": self.meta["run_id"],
                "mode": self.mode,
                "recorded_at": now(),
                "photo_sha256": row["photo"]["sha256"],
                "status": "failed",
                "detections": [],
                "target_box": None,
                "animal_number": None,
                "analysis": None,
                "metrics": {},
                "raw_detection": None,
            }
            try:
                path = self.image_path(key)
                data = path.read_bytes()
                with Image.open(io.BytesIO(data)) as original:
                    pil = ImageOps.exif_transpose(original).convert("RGB")
                    width, height = pil.size
                    buffer = io.BytesIO()
                    pil.save(buffer, format="JPEG", quality=95)
                image = ImageInput(
                    data=buffer.getvalue(), mime_type="image/jpeg", photo_id=key
                )
                client = self.client_factory()
                if target:
                    result["detections"] = previous["detections"]
                    result["raw_detection"] = previous["raw_detection"]
                    if target.manual_box is not None:
                        detection = AnimalDetection(box=target.manual_box)
                        result["target_basis"] = "manual_box"
                    else:
                        number = target.animal_number
                        if number > len(result["detections"]):
                            raise Conflict("Selected animal is outside current detections")
                        detection = AnimalDetection.model_validate(
                            result["detections"][number - 1]
                        )
                        result["animal_number"] = number
                        result["target_basis"] = "human_selected_detection"
                else:
                    detector = DetectionAgent(client)
                    detections = detector.run(images=[image])
                    result["detections"] = detections.model_dump(mode="json")["animals"]
                    result["metrics"].update(detector.last_metrics)
                    result["raw_detection"] = detector.last_response
                    if len(detections.animals) == 1:
                        detection = detections.animals[0]
                        result["animal_number"] = 1
                        result["target_basis"] = "sole_detection_unconfirmed"
                    else:
                        result["status"] = (
                            "no_detection" if not detections.animals else "selection_required"
                        )
                        detection = None
                if detection:
                    y1, x1, y2, x2 = detection.box
                    if (y2 - y1) * height / 1000 < 2 or (x2 - x1) * width / 1000 < 2:
                        raise ValueError("Degenerate detection box; draw a manual target")
                    result["target_box"] = detection.box
                    result["analysis"] = analyze_still(
                        crop_to_detection(image, detection),
                        result["animal_number"] or "manual",
                        client=client,
                        viewpoint="unknown",
                        debug=True,
                    )
                    result["metrics"].update(result["analysis"]["metrics"])
                    result["status"] = "completed"
            except AgentError as exc:
                result["error"] = {
                    "agent": exc.agent,
                    "kind": exc.kind,
                    "attempts": exc.attempts,
                }
            except (LookupError, OSError, ValueError) as exc:
                if isinstance(exc, Conflict):
                    raise
                result["error"] = {"kind": "input_error", "message": str(exc)}
            result["latency_seconds"] = round(time.monotonic() - started, 3)
            atomic_json(
                self.run_dir / "attempts" / key / f"{result['prediction_id']}.json", result
            )
            atomic_json(self.run_dir / "predictions" / f"{key}.json", result)
            return result

    def save_review(self, key, body):
        self.image_path(key)
        # Serialize with analysis on this case, so target provenance cannot race.
        with locked(self.run_dir / "locks" / f"{key}.lock", blocking=False):
            current = self.prediction(key)
            self.check_prediction(current, body.expected_prediction_id)
            previous = self.review(key)
            revision = (previous or {}).get("revision", 0)
            if revision != body.expected_revision:
                raise Conflict("Review changed; refresh before editing")
            entry = {
                **body.model_dump(mode="json"),
                "case_id": key,
                "run_id": self.meta["run_id"],
                "revision": revision + 1,
                "recorded_at": now(),
                "photo_sha256": self.row(key)["photo"]["sha256"],
                "label_status": "provisional_human_review",
                "expert_reviewed": False,
                "qualification_basis": "self-reported; not independently verified",
            }
            atomic_json(
                self.run_dir / "review_history" / key / f"{uuid.uuid4().hex}.json", entry
            )
            atomic_json(self.run_dir / "reviews" / f"{key}.json", entry)
            return entry

    def summary(self):
        statuses, groups, comparison = Counter(), {}, {}
        predicted_groups = Counter()
        reviewed = 0
        metrics = Counter()
        exposed = Counter()
        for key in self.rows:
            prediction, review = self.prediction(key), self.review(key)
            statuses[(prediction or {}).get("status", "not_run")] += 1
            if prediction and prediction["status"] == "completed":
                predicted_groups[
                    prediction["analysis"]["identity_summary"]["animal_group"]
                ] += 1
            if prediction:
                metrics["wall_seconds"] += prediction.get("latency_seconds", 0)
                for name, value in prediction.get("metrics", {}).items():
                    if value is not None and name.endswith(
                        ("_prompt_tokens", "_output_tokens")
                    ):
                        metrics[
                            "prompt_tokens"
                            if name.endswith("_prompt_tokens")
                            else "output_tokens"
                        ] += value
            if not review:
                continue
            reviewed += 1
            exposed["predictions_exposed"] += bool(review["predictions_exposed"])
            exposed["source_exposed"] += bool(review["source_exposed"])
            group = review["animal_group"]
            groups[group] = groups.get(group, 0) + 1
            if not prediction or prediction["status"] != "completed" or self.mode != "live":
                continue
            if (
                review["expected_prediction_id"] != prediction["prediction_id"]
                or review["animal_present"] != "yes"
                or prediction["target_box"] != review["target_box"]
            ):
                continue
            for field, model_field in FLAGS.items():
                counts = comparison.setdefault(group, {}).setdefault(
                    field,
                    {"comparable": 0, "not_assessable": 0, "tp": 0, "fp": 0, "fn": 0, "tn": 0},
                )
                human = review[field]
                if human == "uncertain":
                    counts["not_assessable"] += 1
                    continue
                counts["comparable"] += 1
                model = prediction["analysis"]["assessment"]["injury"][model_field]
                counts[
                    ("tp" if model else "fn")
                    if human == "observed"
                    else ("fp" if model else "tn")
                ] += 1
        return {
            "mode": self.mode,
            "cases": len(self.rows),
            "statuses": dict(statuses),
            "provisionally_reviewed": reviewed,
            "reviewed_groups": groups,
            "predicted_groups": dict(predicted_groups),
            "latest_attempt_metrics": dict(metrics),
            "review_exposure": dict(exposed),
            "provisional_condition_comparison": comparison,
            "expert_reviewed_count": 0,
            "accuracy": None,
            "limitations": [
                "No expert injury ground truth; medical accuracy is unmeasured.",
                "Comparisons require the same selected target; uncertain signs are excluded.",
                "Human annotations are provisional, including self-reported qualifications.",
                "This is an opportunistic development sample, not an aerial benchmark.",
            ],
        }
