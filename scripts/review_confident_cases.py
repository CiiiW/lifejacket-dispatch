#!/usr/bin/env python3
"""Bounded four-case live recheck. No case creation, dispatch, training or condition labels."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lifejacket.agents.detection import DetectionAgent, crop_to_detection  # noqa: E402
from lifejacket.agents.identification import IdentificationAgent  # noqa: E402
from lifejacket.llm.client import ImageInput  # noqa: E402
from lifejacket.services.drone_suggestions import group_confidence, suggest  # noqa: E402

CASES = {
    "eumetopias_jubatus_02",
    "odobenus_rosmarus_01",
    "enhydra_lutris_02",
    "trichechus_manatus_01",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_source(row):
    if row["case_id"] not in CASES or row.get("manifest_photo_attached") is not True:
        raise ValueError("Source photo/observation not verified")
    reference = row["reference_species"].lower()
    current = (row.get("current_taxon_name") or "").lower()
    if current != reference and not current.startswith(reference + " "):
        raise ValueError("Current source taxon disagrees with reference")
    path = Path(row["download_file"])
    data = path.read_bytes()
    if sha(data) != row["download_sha256"]:
        raise ValueError("Source image fingerprint changed")
    return path, data


def identification(agent, image, context):
    result = agent.run(
        images=[image],
        location_summary="Location unavailable; do not infer a location.",
        questions_remaining=0,
        target_context=context,
    )
    serialized = result.model_dump(mode="json")
    top = max(result.candidates, key=lambda c: c.confidence) if result.candidates else None
    replay = suggest(
        SimpleNamespace(
            status="awaiting_dispatch",
            duplicate_of=None,
            identification_json=serialized,
            assessment_json=None,
            latitude=None,
            longitude=None,
            severity_level=None,
            entanglement_present=False,
        ),
        0.9,
    )
    return {
        "identification": serialized,
        "raw_response": agent.last_response,
        "metrics": agent.last_metrics,
        "model": agent.client.model,
        "reported_group": result.animal_group.value,
        "pooled_group_confidence": group_confidence(serialized),
        "top_species": top.scientific_name if top else None,
        "verification_suggested_in_constructed_replay": replay is not None,
        "suggestion_signals": [s["code"] for s in replay["signals"]] if replay else [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    rows = json.loads((args.input_dir / "source_audit.json").read_text())
    if len(rows) != 4 or {r["case_id"] for r in rows} != CASES:
        raise ValueError("Expected exactly the four preselected disagreement cases")
    prepared = []
    for row in rows:
        _, content = verify_source(row)
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
        data = buffer.getvalue()
        opaque_id = sha(data)[:16]
        prepared.append(
            (row, ImageInput(data=data, mime_type="image/jpeg", photo_id=opaque_id))
        )
        (args.input_dir / (row["case_id"] + ".prepared.jpg")).write_bytes(data)
    if not args.live:
        print("Verified four inputs; use --live to run the current model.")
        return
    output = args.input_dir / "current_predictions.json"
    if output.exists():
        raise ValueError("Existing live run is immutable; choose a new run directory")
    identifier = IdentificationAgent()
    detector = DetectionAgent(identifier.client)
    tracked = [
        "prompts/system_principles.md",
        "prompts/identification/identify_species.md",
        "prompts/identification/detect_animals.md",
        "backend/lifejacket/agents/identification.py",
        "backend/lifejacket/agents/detection.py",
        "backend/lifejacket/llm/client.py",
        "backend/lifejacket/models/schemas.py",
        "backend/lifejacket/taxonomy.py",
        "scripts/review_confident_cases.py",
    ]
    report = {
        "mode": "live",
        "started_at": datetime.now(UTC).isoformat(),
        "model": identifier.client.model,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {p: sha(Path(p).read_bytes()) for p in tracked},
        "input_policy": (
            "EXIF removed; opaque image IDs; no species, source text or location supplied."
        ),
        "selection_policy": (
            "Use only a sole detector target. Zero/multiple detections remain unresolved."
        ),
        "source_photos_have_october_hashes": False,
        "independent_holdout": False,
        "expert_review": False,
        "cases": [],
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    for source, image in prepared:
        row = {
            "case_id": source["case_id"],
            "prepared_sha256": sha(image.data),
            "original_sha256": source["download_sha256"],
            "reference_group": source["reference_group"],
        }
        try:
            row["full_image"] = identification(
                identifier,
                image,
                "Analyze the active photo. "
                "No source labels or geographic context are supplied. "
                "No live reporter is available; "
                "retain uncertainty if the view is inadequate.",
            )
        except Exception as exc:
            row["full_image_error"] = type(exc).__name__ + ": " + str(exc)[:300]
        try:
            detection = detector.run(images=[image])
            row["detection"] = detection.model_dump(mode="json")
            row["detection_metrics"] = detector.last_metrics
            if len(detection.animals) == 1:
                crop = crop_to_detection(image, detection.animals[0])
                (args.input_dir / (source["case_id"] + ".crop.jpg")).write_bytes(crop.data)
                row["crop_sha256"] = sha(crop.data)
                row["selected_crop"] = identification(
                    identifier,
                    crop,
                    "Analyze the selected animal crop. No source labels or geographic context "
                    "are supplied. No live reporter is available; "
                    "retain uncertainty if inadequate.",
                )
            else:
                row["crop_status"] = (
                    "no_detection" if not detection.animals else "selection_required"
                )
        except Exception as exc:
            row["detection_or_crop_error"] = type(exc).__name__ + ": " + str(exc)[:300]
        report["cases"].append(row)
        output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(
            source["case_id"],
            row.get("full_image", {}).get("reported_group"),
            row.get("full_image", {}).get("pooled_group_confidence"),
            "detections",
            len(row.get("detection", {}).get("animals", [])),
            "crop",
            row.get("selected_crop", {}).get("reported_group"),
            row.get("detection_or_crop_error") or row.get("full_image_error") or "",
            flush=True,
        )
    report["finished_at"] = datetime.now(UTC).isoformat()
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(output)


if __name__ == "__main__":
    main()
