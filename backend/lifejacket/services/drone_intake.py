"""Review real drone evidence and prepare a manual handoff to a directory center.

No outbound network calls, inferred availability, or automatic dispatch.
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, object_session

from lifejacket.dispatch.matching import center_id, load_rescue_centers, score_area_match
from lifejacket.models import repository
from lifejacket.models.drone_intake import (
    ContactUpdate,
    LinkCase,
    PrepareHandoff,
    ReviewObservation,
)
from lifejacket.models.schemas import (
    AnimalGroup,
    AssessmentResult,
    GeoPoint,
    IdentificationResult,
    Incident,
    IncidentReport,
    IncidentStatus,
)
from lifejacket.models.tables import DroneAnalysisRow, DroneObservationRow, ExternalHandoffRow
from lifejacket.services.events import record_event

TRANSITIONS = {
    "draft": {"contact_attempted", "escalated"},
    "contact_attempted": {"acknowledged", "declined", "escalated"},
    "acknowledged": {"accepted", "declined", "escalated"},
    "accepted": {"completed", "escalated"},
    "declined": set(),
    "escalated": set(),
    "completed": set(),
}


class Conflict(ValueError):
    pass


def observation(session: Session, observation_id: str) -> DroneObservationRow:
    row = session.get(DroneObservationRow, observation_id)
    if row is None:
        raise LookupError("Observation not found")
    return row


def latest_analysis(row: DroneObservationRow):
    session = object_session(row)
    if session is None:
        return None
    analysis = session.scalar(
        select(DroneAnalysisRow)
        .where(DroneAnalysisRow.observation_id == row.observation_id)
        .order_by(DroneAnalysisRow.id.desc())
        .limit(1)
    )
    return {"analysis_id": analysis.id, **analysis.payload_json} if analysis else None


def observation_out(row: DroneObservationRow) -> dict:
    return {
        "observation_id": row.observation_id,
        "status": row.status,
        "revision": row.revision,
        "source_kind": row.source_kind,
        "run_id": row.run_id,
        "metadata": row.metadata_json,
        "sha256": row.sha256,
        "photo_url": f"/drone-intake/observations/{row.observation_id}/photo",
        "review": row.review_json,
        "incident_id": row.incident_id,
        "created_at": row.created_at.isoformat(),
        "analysis": latest_analysis(row),
    }


def _revise(session, row, expected, **changes):
    model = type(row)
    key = "observation_id" if model is DroneObservationRow else "handoff_id"
    result = session.execute(
        update(model)
        .where(getattr(model, key) == getattr(row, key), model.revision == expected)
        .values(revision=expected + 1, **changes),
        execution_options={"synchronize_session": False},
    )
    if result.rowcount != 1:
        raise Conflict("Record changed; refresh and review again")
    session.expire(row)
    session.refresh(row)


def review(session: Session, row: DroneObservationRow, body: ReviewObservation) -> dict:
    if row.incident_id:
        raise Conflict("Evidence is already linked; use the case history for corrections")
    entry = {
        "decision": body.decision,
        "note": body.note,
        "actor": body.actor,
        "recorded_at": datetime.now(UTC).isoformat(),
        "identity_basis": "coordinator-entered; not authenticated",
        "analysis_id": (latest_analysis(row) or {}).get("analysis_id"),
    }
    history = [*(row.review_json or {}).get("history", []), entry]
    _revise(
        session,
        row,
        body.expected_revision,
        status=body.decision,
        review_json={**entry, "history": history},
    )
    session.commit()
    return observation_out(row)


def screen_photo(session, row, body, *, identify=False, client=None):
    from lifejacket.services import drone_vision

    if row.incident_id:
        raise Conflict("Evidence is already linked; use case assessment for further review")
    if row.revision != body.expected_revision:
        raise Conflict("Observation changed; refresh before analysis")
    if identify:
        previous = latest_analysis(row)
        if (
            not previous
            or previous["analysis_id"] != body.detection_id
            or previous["stage"] != "detected"
        ):
            raise Conflict("Refresh detections before selecting an animal")
        detections = previous["detections"]
        if body.animal_number > len(detections):
            raise Conflict("Select one of the detected animals")
        payload = drone_vision.analyze(
            row, detections[body.animal_number - 1], body.animal_number, client
        )
        payload.update(detection_id=body.detection_id, detections=detections)
    else:
        payload = drone_vision.detect(row, client)
    payload.update(
        actor=body.actor,
        recorded_at=datetime.now(UTC).isoformat(),
        source_kind=row.source_kind,
        evidence_sha256=row.sha256,
    )
    # A new analysis requires fresh review, even if this photo was verified before.
    _revise(session, row, body.expected_revision, status="pending")
    session.add(DroneAnalysisRow(observation_id=row.observation_id, payload_json=payload))
    session.commit()
    return observation_out(row)


def link_case(session: Session, row: DroneObservationRow, body: LinkCase) -> dict:
    if row.source_kind != "real" or row.status != "verified":
        raise Conflict("Only coordinator-verified real evidence can enter a rescue case")
    if row.incident_id:
        return observation_out(row)
    if body.existing_incident_id:
        incident = repository.load_incident(session, body.existing_incident_id)
        if incident is None:
            raise LookupError("Case not found")
    else:
        incident = Incident(
            incident_id=repository.new_incident_id(),
            status=IncidentStatus.ASSESSING,
            reporter_id="drone_coordinator",
            location=GeoPoint(
                latitude=row.latitude, longitude=row.longitude, source="manual_entry"
            ),
            report=IncidentReport(
                headline="Coordinator-reviewed drone observation; assessment pending",
                summary=row.metadata_json["description"],
                unknowns=["Species, injury severity and response priority require assessment"],
            ),
            metrics={
                "source": "drone_observation",
                "observation_id": row.observation_id,
                "capture_time": row.metadata_json["observed_at"],
                "drone_intake_pending_assessment": True,
            },
        )
        analysis = latest_analysis(row)
        if analysis and analysis["stage"] == "assessed":
            incident.identification = IdentificationResult.model_validate(
                analysis["identification"]
            )
            incident.assessment = AssessmentResult.model_validate(analysis["assessment"])
            incident.assessment.requires_human_review = True
            incident.metrics.update(
                drone_analysis_id=analysis["analysis_id"],
                drone_analysis_limitations=analysis["limitations"],
                severity_reasons=analysis["severity_reasons"],
            )
            incident.report.summary += " Advisory photo screening: " + (
                incident.assessment.injury.summary or "condition uncertain"
            )
            incident.report.unknowns.extend(analysis["limitations"])
    repository.save_incident(session, incident)
    _revise(session, row, body.expected_revision, incident_id=incident.incident_id)
    repository.save_photo(
        session,
        incident.incident_id,
        row.storage_path,
        row.content_type,
    )
    record_event(
        session,
        incident.incident_id,
        "drone_evidence_verified",
        {
            "observation_id": row.observation_id,
            "sha256": row.sha256,
            "review": row.review_json,
            "source_kind": "real",
            "analysis_id": (latest_analysis(row) or {}).get("analysis_id"),
        },
        body.actor,
    )
    session.commit()
    return observation_out(row)


def directory_candidates(row: DroneObservationRow) -> list[dict]:
    analysis = latest_analysis(row) or {}
    identity = analysis.get("identity_summary", {})
    group = (
        identity.get("animal_group")
        if identity.get("is_confident")
        else row.metadata_json.get("animal_group")
    )
    if group in {AnimalGroup.TERRESTRIAL.value, AnimalGroup.DOMESTIC_ANIMAL.value}:
        return []  # Same unsupported groups as the chatbot's marine directory.
    result = []
    generic = {"california", "oregon", "washington", "united states", "usa"}
    terms = [
        re.sub(r"\bcount(?:y|ies)\b", "", term.casefold()).strip()
        for term in row.metadata_json["area_terms"]
    ]
    terms = [term for term in terms if len(term) >= 3 and term not in generic]
    for center in load_rescue_centers():
        score = score_area_match(center.response_area, terms)
        if score <= 0:
            continue
        result.append(
            {
                "center_id": center_id(center.center_name),
                "name": center.center_name,
                "hotline": center.hotline,
                "phone": center.phone,
                "email": center.email,
                "website": center.website,
                "response_area": center.response_area,
                "response_type": center.response_type,
                "directory_source": center.source,
                "area_match": score,
                "availability": "unknown",
                "registration_required": False,
                "contact_and_capability_verification_required": True,
            }
        )
    return sorted(result, key=lambda x: (-x["area_match"], x["name"]))


def handoff_out(row: ExternalHandoffRow) -> dict:
    return {
        "handoff_id": row.handoff_id,
        "observation_id": row.observation_id,
        "incident_id": row.incident_id,
        "status": row.status,
        "revision": row.revision,
        "snapshot": row.snapshot_json,
        "history": row.history_json,
        "outbound_message_sent": False,
        "status_basis": "coordinator-reported external contact",
    }


def prepare(session: Session, row: DroneObservationRow, body: PrepareHandoff) -> dict:
    if row.source_kind != "real" or row.status != "verified" or not row.incident_id:
        raise Conflict(
            "Link verified real evidence to a case before preparing external contact"
        )
    if row.revision != body.expected_revision:
        raise Conflict("Observation changed; refresh before handoff")
    candidate = next(
        (c for c in directory_candidates(row) if c["center_id"] == body.center_id), None
    )
    if candidate is None:
        raise Conflict(
            "Selected center has no directory area match; escalate for manual routing"
        )
    if not (candidate["hotline"] or candidate["phone"] or candidate["email"]):
        raise Conflict("No usable directory contact")
    active = session.scalar(
        select(ExternalHandoffRow).where(
            ExternalHandoffRow.observation_id == row.observation_id,
            ExternalHandoffRow.status.in_(
                ["draft", "contact_attempted", "acknowledged", "accepted"]
            ),
        )
    )
    if active:
        if active.center_id == body.center_id:
            return handoff_out(active)
        raise Conflict(
            "Resolve or escalate the active handoff before contacting another center"
        )
    # Claim observation revision in the same transaction to serialize concurrent drafts.
    _revise(session, row, body.expected_revision)
    analysis = latest_analysis(row) or {}
    analysis_text = ""
    if analysis.get("stage") == "assessed":
        identity = analysis["identity_summary"]
        analysis_text = (
            f"Advisory AI screening of selected animal {analysis['animal_number']}: "
            f"{identity['name']} ({identity['animal_group']}); "
            f"{analysis['assessment']['injury'].get('summary') or 'condition uncertain'}.\n"
            "Aerial model performance is unvalidated; findings require expert review.\n"
        )
    packet = {
        "center": candidate,
        "evidence": observation_out(row),
        "contact_verified_by": body.actor,
        "verification_source": str(body.verification_source),
        "verification_note": body.verification_note,
        "verified_at": datetime.now(UTC).isoformat(),
        "registration_required": False,
        "availability": "unknown",
        "packet_text": (
            f"LifeJacket case {row.incident_id} — coordinator-reviewed drone observation.\n"
            f"Observed {row.metadata_json['observed_at']} "
            f"at {row.latitude}, {row.longitude}.\n"
            f"Operator description: {row.metadata_json['description']}\n"
            "Operator animal-group hint (unconfirmed): "
            f"{row.metadata_json.get('animal_group', 'unknown')}.\n"
            f"{analysis_text}"
            "Species and medical severity are unconfirmed. Please advise on response.\n"
            f"Evidence reference: {row.observation_id}; SHA-256 {row.sha256}."
        ),
    }
    handoff = ExternalHandoffRow(
        handoff_id=uuid.uuid4().hex,
        observation_id=row.observation_id,
        incident_id=row.incident_id,
        center_id=body.center_id,
        status="draft",
        revision=0,
        snapshot_json=packet,
        history_json=[
            {
                "status": "draft",
                "actor": body.actor,
                "note": "Prepared for manual contact; nothing sent",
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        ],
    )
    session.add(handoff)
    record_event(
        session,
        row.incident_id,
        "external_handoff_prepared",
        {"handoff_id": handoff.handoff_id, "center_id": body.center_id},
        body.actor,
    )
    session.commit()
    return handoff_out(handoff)


def contact_update(session: Session, row: ExternalHandoffRow, body: ContactUpdate) -> dict:
    if body.status not in TRANSITIONS[row.status]:
        raise Conflict(f"Cannot move from {row.status} to {body.status}")
    history = [
        *row.history_json,
        {
            "status": body.status,
            "actor": body.actor,
            "note": body.note,
            "channel": body.channel,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
    ]
    _revise(session, row, body.expected_revision, status=body.status, history_json=history)
    record_event(
        session,
        row.incident_id,
        "external_contact_recorded",
        {
            "handoff_id": row.handoff_id,
            "status": body.status,
            "channel": body.channel,
            "note": body.note,
            "basis": "coordinator report; no automated delivery",
        },
        body.actor,
    )
    # Preserve app assignment/ETA state. This record is not an app acceptance.
    session.commit()
    return handoff_out(row)
