"""Explicit saved-frame AI jobs. Results never overwrite intake or dispatch."""

import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from lifejacket.access.memberships import membership_context
from lifejacket.access.policy import Principal, Role
from lifejacket.agents.detection import DetectionAgent, crop_to_detection
from lifejacket.config import settings
from lifejacket.llm.client import ImageInput
from lifejacket.models.schemas import AnimalDetection
from lifejacket.models.tables import (
    AccessUserRow,
    CaseDroneAnalysisRow,
    CaseDroneEvidenceRow,
    CaseDroneRequestRow,
)
from lifejacket.services import drone_followup as common
from lifejacket.services import drone_requests as requests
from lifejacket.services.drone_vision import LIMITATIONS, analyze_still


def enabled():
    if not (
        settings.network_auth_enabled
        and settings.case_drone_requests_enabled
        and settings.drone_frame_analysis_enabled
    ):
        raise HTTPException(503, "Frame analysis is not configured")


def out(row):
    return {
        "analysis_id": row.analysis_id,
        "evidence_id": row.evidence_id,
        "status": row.status,
        "stage": row.input_json["stage"],
        "detection_job_id": row.input_json.get("detection_job_id"),
        "animal_index": row.input_json.get("animal_index"),
        "request_key": row.request_key,
        "result": row.result_json,
        "error_code": row.error_code,
        "attempts": row.attempts,
        "created_at": row.created_at.isoformat() + "Z",
        "requires_human_review": True,
    }


def enqueue(db, actor, case_id, request_id, evidence_id, body):
    requests.access(db, actor, case_id, write=True)
    request = requests.get(db, case_id, request_id)
    if request.status not in {"in_progress", "evidence_ready"} or not common.eligible(
        db, request, actor.organization_id
    ):
        raise HTTPException(409, "Observation is no longer accepting analysis")
    evidence = db.get(CaseDroneEvidenceRow, evidence_id)
    if evidence is None or evidence.request_id != request_id:
        raise HTTPException(404, "Evidence unavailable")
    data = {
        "stage": body.stage,
        "detection_job_id": body.detection_job_id,
        "animal_index": body.animal_index,
        "sha256": evidence.sha256,
        "model": settings.llm_model,
    }
    if body.stage == "assess":
        detected = db.get(CaseDroneAnalysisRow, body.detection_job_id)
        if not (
            detected
            and detected.request_id == request_id
            and detected.evidence_id == evidence_id
            and detected.status == "completed"
            and detected.input_json["stage"] == "detect"
            and detected.input_json["sha256"] == evidence.sha256
            and body.animal_index < len(detected.result_json["detections"])
        ):
            raise HTTPException(
                409, "Choose an animal from a completed detection for this frame"
            )
    previous = db.scalar(
        select(CaseDroneAnalysisRow).where(
            CaseDroneAnalysisRow.request_id == request_id,
            CaseDroneAnalysisRow.request_key == body.request_key,
        )
    )
    if previous:
        if previous.input_json != data or previous.evidence_id != evidence_id:
            raise HTTPException(409, "Analysis key was used for different evidence")
        if previous.status != "failed":
            return {**out(previous), "revision": request.revision}
        row = previous
        row.status = "queued"
        row.attempts = 0
        row.error_code = None
        row.requested_by = actor.user_id
        row.organization_id = actor.organization_id
        row.next_attempt_at = requests.now()
        row.updated_at = requests.now()
    else:
        row = CaseDroneAnalysisRow(
            analysis_id=uuid.uuid4().hex,
            request_id=request_id,
            evidence_id=evidence_id,
            request_key=body.request_key,
            requested_by=actor.user_id,
            organization_id=actor.organization_id,
            status="queued",
            attempts=0,
            next_attempt_at=requests.now(),
            input_json=data,
            result_json=None,
            created_at=requests.now(),
            updated_at=requests.now(),
        )
        db.add(row)
    requests.compare_swap(db, request, body.revision)
    requests.event(
        db,
        request,
        actor,
        "frame_analysis_queued",
        {"analysis_id": row.analysis_id, "evidence_id": evidence_id, "stage": body.stage},
    )
    db.commit()
    return {**out(row), "revision": request.revision}


def authorized(db, row):
    user = db.get(AccessUserRow, row.requested_by)
    if not user or not user.enabled:
        return False
    try:
        _, _, role, states = membership_context(db, user.user_id, row.organization_id)
        actor = Principal(
            user.user_id,
            role,
            identity_verified=True,
            organization_id=row.organization_id,
            membership_verified=True,
            allowed_states=states,
        )
        request = db.get(CaseDroneRequestRow, row.request_id)
        if not request or request.status not in {"in_progress", "evidence_ready"}:
            return False
        requests.access(db, actor, request.incident_id, write=True)
        return role == Role.CENTER_COORDINATOR and common.eligible(
            db, request, row.organization_id
        )
    except Exception:
        return False


def image_for(evidence):
    data = Path(evidence.storage_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != evidence.sha256:
        raise ValueError("evidence_integrity")
    return ImageInput(
        data=data, mime_type=evidence.content_type, photo_id=evidence.evidence_id
    )


def infer(db, row, client=None):
    evidence = db.get(CaseDroneEvidenceRow, row.evidence_id)
    if not evidence or evidence.sha256 != row.input_json["sha256"]:
        raise ValueError("evidence_integrity")
    image = image_for(evidence)
    if row.input_json["stage"] == "detect":
        db.commit()
        agent = DetectionAgent(client)
        result = agent.run(images=[image])
        return {
            "detections": result.model_dump(mode="json")["animals"][:32],
            "limitations": ["Advisory still-photo screening; viewpoint is unverified."]
            + LIMITATIONS[1:],
            "model": agent.client.model,
            "metrics": agent.last_metrics,
        }
    detected = db.get(CaseDroneAnalysisRow, row.input_json["detection_job_id"])
    detection = AnimalDetection.model_validate(
        detected.result_json["detections"][row.input_json["animal_index"]]
    )
    crop = crop_to_detection(image, detection)
    db.commit()
    return analyze_still(
        crop,
        row.input_json["animal_index"] + 1,
        client=client,
        viewpoint="unknown",
        observed_at=evidence.metadata_json.get("captured_at"),
    )


def process_one(factory, runner=infer):
    enabled()
    with factory() as db:
        common.heartbeat(db, "analysis")
        row = db.scalar(
            select(CaseDroneAnalysisRow)
            .where(common.claimable(CaseDroneAnalysisRow, requests.now()))
            .order_by(CaseDroneAnalysisRow.created_at)
            .limit(1)
        )
        if row is None:
            return False
        token = common.claim(db, CaseDroneAnalysisRow, row)
        if not token:
            return False
        if not authorized(db, row):
            common.finish(
                db,
                CaseDroneAnalysisRow,
                row,
                token,
                "cancelled",
                error_code="authorization_changed",
            )
            return True
        if row.attempts > 2:
            common.finish(
                db, CaseDroneAnalysisRow, row, token, "failed", error_code="worker_interrupted"
            )
            return True
        # Close the transaction before external model work. Recheck access afterward.
        db.commit()
        try:
            result = runner(db, row)
            db.expire_all()
            if not authorized(db, row):
                common.finish(
                    db,
                    CaseDroneAnalysisRow,
                    row,
                    token,
                    "cancelled",
                    error_code="authorization_changed",
                )
            else:
                common.finish(
                    db,
                    CaseDroneAnalysisRow,
                    row,
                    token,
                    "completed",
                    result_json=result,
                    error_code=None,
                )
        except Exception:
            db.rollback()
            common.finish(
                db, CaseDroneAnalysisRow, row, token, "failed", error_code="analysis_failed"
            )
        return True
