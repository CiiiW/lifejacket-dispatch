"""Attach validated detector output to immutable, case-scoped saved evidence."""

import hashlib
import io
import uuid
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps
from sqlalchemy import select

from lifejacket.models.tables import CaseDroneAnalysisRow, CaseDroneEvidenceRow
from lifejacket.services import drone_followup as common
from lifejacket.services import drone_frame_analysis as analysis
from lifejacket.services import drone_requests as requests


def attach(db, actor, case_id, request_id, evidence_id, body):
    requests.access(db, actor, case_id, write=True)
    request = requests.get(db, case_id, request_id)
    if request.status not in {"in_progress", "evidence_ready"} or not common.eligible(
        db, request, actor.organization_id
    ):
        raise HTTPException(409, "Observation is no longer accepting detector results")
    evidence = db.get(CaseDroneEvidenceRow, evidence_id)
    if evidence is None or evidence.request_id != request_id:
        raise HTTPException(404, "Evidence unavailable")
    result = body.result
    if result.evidence_id != evidence_id or result.source_sha256 != evidence.sha256:
        raise HTTPException(409, "Detector result does not match this saved evidence")
    if result.source_kind != evidence.metadata_json["source_kind"]:
        raise HTTPException(409, "Detector source provenance does not match saved evidence")
    try:
        data = Path(evidence.storage_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != result.source_sha256:
            raise ValueError("integrity")
        with Image.open(io.BytesIO(data)) as image:
            if ImageOps.exif_transpose(image).size != (result.width, result.height):
                raise ValueError("dimensions")
        detections = result.agent_detections() if result.status == "completed" else []
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Source image integrity or dimensions do not match") from exc
    payload = {
        "stage": "detect",
        "sha256": evidence.sha256,
        "provider": "external_detector",
        "model": result.model_name,
        "detector_result": result.model_dump(mode="json"),
    }
    previous = db.scalar(
        select(CaseDroneAnalysisRow).where(
            CaseDroneAnalysisRow.request_id == request_id,
            CaseDroneAnalysisRow.request_key == body.request_key,
        )
    )
    if previous:
        if previous.evidence_id != evidence_id or previous.input_json != payload:
            raise HTTPException(409, "Detector key was used for different evidence or output")
        return {**analysis.out(previous), "revision": request.revision}
    now = requests.now()
    row = CaseDroneAnalysisRow(
        analysis_id=uuid.uuid4().hex,
        request_id=request_id,
        evidence_id=evidence_id,
        request_key=body.request_key,
        requested_by=actor.user_id,
        organization_id=actor.organization_id,
        status=result.status,
        attempts=0,
        next_attempt_at=now,
        input_json=payload,
        result_json={
            "detections": detections,
            "model": result.model_name,
            "model_version": result.model_version,
            "weights_sha256": result.weights_sha256,
            "detector_candidates": [d.model_dump(mode="json") for d in result.detections],
            "limitations": [
                "External detector output; accuracy is unvalidated here.",
                "No detection does not establish animal absence.",
                "Track IDs do not establish identity across flights.",
            ],
        },
        error_code=result.error_code,
        created_at=now,
        updated_at=now,
    )
    requests.compare_swap(db, request, body.revision)
    db.add(row)
    requests.event(
        db,
        request,
        actor,
        "detector_result_attached",
        {
            "analysis_id": row.analysis_id,
            "evidence_id": evidence_id,
            "provider": "external_detector",
            "status": row.status,
        },
    )
    db.commit()
    return {**analysis.out(row), "revision": request.revision}


def source(db, actor, case_id, request_id, evidence_id):
    requests.access(db, actor, case_id)
    requests.get(db, case_id, request_id)
    evidence = db.get(CaseDroneEvidenceRow, evidence_id)
    if evidence is None or evidence.request_id != request_id:
        raise HTTPException(404, "Evidence unavailable")
    try:
        data = Path(evidence.storage_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != evidence.sha256:
            raise ValueError("integrity")
        with Image.open(io.BytesIO(data)) as image:
            width, height = ImageOps.exif_transpose(image).size
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Saved evidence integrity check failed") from exc
    return {
        "evidence_id": evidence_id,
        "source_sha256": evidence.sha256,
        "width": width,
        "height": height,
        "source_kind": evidence.metadata_json["source_kind"],
        "coordinate_note": "Pixel XYXY after orientation normalization; undo letterboxing.",
    }
