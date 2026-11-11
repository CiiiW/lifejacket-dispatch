"""Detector output is evidence-scoped, idempotent and feeds existing assessment."""

import hashlib
from pathlib import Path

from lifejacket.llm.fake import ScriptedLLMClient
from lifejacket.models.tables import CaseDroneAnalysisRow, CaseDroneEvidenceRow, IncidentRow
from lifejacket.services import drone_frame_analysis as ai
from test_drone_followup import evidence, followup_api, queue  # noqa: F401
from test_drone_requests import BASE, drone_api  # noqa: F401
from test_network_actions import actor, api  # noqa: F401


def payload(client, row, eid, **extra):
    path = BASE + "/" + row["request_id"] + "/evidence/" + eid
    source = client.get(path + "/detector-input")
    assert source.status_code == 200, source.text
    metadata = source.json()
    return {
        "revision": row["revision"],
        "confirmed": True,
        "request_key": "detector-one",
        "result": {
            k: metadata[k]
            for k in ("evidence_id", "source_sha256", "width", "height", "source_kind")
        }
        | {
            "schema_version": 1,
            "model_name": "teammate-fixture",
            "model_version": "v1",
            "weights_sha256": "a" * 64,
            "status": "completed",
            "detections": [
                {"class_name": "left candidate", "confidence": 0.8, "xyxy": [0, 0, 6, 12]},
                {"class_name": "right candidate", "confidence": 0.7, "xyxy": [6, 0, 12, 12]},
            ],
            "error_code": None,
            **extra,
        },
    }


def endpoint(row, eid):
    return BASE + "/" + row["request_id"] + "/evidence/" + eid + "/detector-result"


def test_detector_handoff_continues_to_selected_animal_assessment(followup_api):  # noqa: F811
    client, factory, _ = followup_api
    row, eid = evidence(client)
    body = payload(client, row, eid)
    attached = client.post(endpoint(row, eid), json=body)
    assert attached.status_code == 201, attached.text
    job = attached.json()
    assert job["provider"] == "external_detector" and job["status"] == "completed"
    assert len(job["result"]["detections"]) == 2
    again = client.post(endpoint(row, eid), json=body)
    assert again.status_code == 201 and again.json()["analysis_id"] == job["analysis_id"]
    row["revision"] = job["revision"]
    assessed = queue(
        client,
        row,
        eid,
        stage="assess",
        request_key="selected-second",
        detection_job_id=job["analysis_id"],
        animal_index=1,
    )
    assert assessed.status_code == 202, assessed.text
    scripted = ScriptedLLMClient.scenario("sea_lion")
    assert ai.process_one(factory, lambda db, job: ai.infer(db, job, scripted))
    assert {call.agent for call in scripted.calls} == {"identification", "assessment"}
    with factory() as db:
        finding = db.get(CaseDroneAnalysisRow, assessed.json()["analysis_id"])
        assert finding.status == "completed", finding.error_code
        assert finding.result_json["animal_number"] == 2
        assert finding.result_json["assessment"]["requires_human_review"] is True
        assert db.get(IncidentRow, "case").assessment_json is None
        assert db.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}
    body["result"]["model_version"] = "different"
    assert client.post(endpoint(row, eid), json=body).status_code == 409


def test_detector_rejects_hash_dimensions_provenance_and_missing_confirmation(followup_api):  # noqa: F811
    client, _, _ = followup_api
    row, eid = evidence(client)
    for changed in (
        {"source_sha256": "f" * 64},
        {"width": 24},
        {"source_kind": "operator_capture"},
        {"evidence_id": "b" * 32},
    ):
        assert (
            client.post(
                endpoint(row, eid), json=payload(client, row, eid, **changed)
            ).status_code
            == 409
        )
    body = payload(client, row, eid)
    body["confirmed"] = False
    assert client.post(endpoint(row, eid), json=body).status_code == 422


def test_failed_detector_is_not_empty_success_and_cannot_be_assessed(followup_api):  # noqa: F811
    client, _, _ = followup_api
    row, eid = evidence(client)
    body = payload(
        client, row, eid, status="failed", detections=[], error_code="model_unavailable"
    )
    response = client.post(endpoint(row, eid), json=body)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["status"] == "failed" and job["error_code"] == "model_unavailable"
    row["revision"] = job["revision"]
    assert (
        queue(
            client,
            row,
            eid,
            stage="assess",
            detection_job_id=job["analysis_id"],
            animal_index=0,
        ).status_code
        == 409
    )
    empty = payload(client, row, eid, detections=[])
    empty["request_key"] = "empty-success"
    response = client.post(endpoint(row, eid), json=empty)
    assert response.status_code == 201
    assert (
        response.json()["status"] == "completed"
        and response.json()["result"]["detections"] == []
    )


def test_detector_access_and_source_integrity(followup_api):  # noqa: F811
    client, factory, current = followup_api
    row, eid = evidence(client)
    body = payload(client, row, eid)
    current[0] = actor("C")
    assert client.post(endpoint(row, eid), json=body).status_code in {403, 404}
    current[0] = actor()
    with factory() as db:
        source = db.get(CaseDroneEvidenceRow, eid)
        assert (
            hashlib.sha256(Path(source.storage_path).read_bytes()).hexdigest() == source.sha256
        )
        Path(source.storage_path).write_bytes(b"corrupt")
    assert client.post(endpoint(row, eid), json=body).status_code == 409
    source_path = BASE + "/" + row["request_id"] + "/evidence/" + eid + "/detector-input"
    assert client.get(source_path).status_code == 409
