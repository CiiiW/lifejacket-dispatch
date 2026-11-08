# ruff: noqa: E402
"""Opt-in live queued-frame integration check using one licensed wildlife photo.

Synthetic case/identity, real model worker; no notifications, aircraft or production DB.
"""

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
from lifejacket.config import settings
from lifejacket.models.tables import (
    CaseDroneAnalysisRow,
    CaseDroneEvidenceRow,
    CaseDroneReminderRow,
    IncidentRow,
    NetworkCaseRow,
)
from lifejacket.services import drone_frame_analysis as analysis
from test_drone_followup import followup_api
from test_drone_requests import BASE, change, drone_api, start
from test_network_actions import api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--animal-index", type=int)
    args = parser.parse_args()
    root = args.input_dir.resolve()
    if (root / "result.json").exists():
        parser.error("Existing live result is protected; use a fresh input directory")
    source = json.loads((root / "source.json").read_text())
    image = (root / "prepared.jpg").read_bytes()
    if hashlib.sha256(image).hexdigest() != source["prepared_sha256"]:
        parser.error("Input hash mismatch")
    result = {
        "source": source,
        "run_kind": "live_model_queued_pipeline",
        "synthetic_case_identity": True,
        "started_at": time.time(),
        "jobs": [],
        "checks": {},
        "scope_limit": (
            "One non-aerial real-photo integration check; "
            "not a model-accuracy or clinical validation."
        ),
    }
    monkey = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory(prefix="lifejacket-live-frame-") as temp:
            directory = Path(temp)
            generator = api.__wrapped__(directory, monkey)
            context = next(generator)
            try:
                context = drone_api.__wrapped__(context, monkey, directory)
                client, factory, _ = followup_api.__wrapped__(context, monkey)
                monkey.setattr(settings, "drone_reminders_enabled", False)
                monkey.setattr(settings, "drone_reminder_webhooks", {})
                monkey.setattr(settings, "drone_reminder_signing_keys", {})
                row = start(client)
                request_path = BASE + "/" + row["request_id"]
                with factory() as db:
                    incident = db.get(IncidentRow, "case")
                    original = copy.deepcopy(
                        {
                            "report": incident.report_json,
                            "assessment": incident.assessment_json,
                            "identification": incident.identification_json,
                        }
                    )
                    original_phase = db.get(NetworkCaseRow, "case").response_phase
                metadata = {
                    "revision": row["revision"],
                    "source_kind": "sample_footage",
                    "source_url": source["observation_url"],
                    "rights_note": str(source["attribution"])
                    + "; "
                    + source["license"]
                    + "; real still photo, not drone footage.",
                    "description": "Saved wildlife still for queued pipeline validation.",
                    "captured_at": None,
                    "frame_offset_seconds": None,
                }
                uploaded = client.post(
                    request_path + "/evidence",
                    data={"metadata": json.dumps(metadata)},
                    files={"photo": ("prepared.jpg", image, "image/jpeg")},
                )
                assert uploaded.status_code == 201, uploaded.text
                eid = uploaded.json()["evidence_id"]
                row["revision"] = uploaded.json()["revision"]
                env = {
                    **os.environ,
                    "DATABASE_URL": str(factory.kw["bind"].url),
                    "NETWORK_AUTH_ENABLED": "true",
                    "CASE_DRONE_REQUESTS_ENABLED": "true",
                    "DRONE_FRAME_ANALYSIS_ENABLED": "true",
                    "DRONE_REMINDERS_ENABLED": "false",
                    "DRONE_REMINDER_WEBHOOKS": "{}",
                    "DRONE_REMINDER_SIGNING_KEYS": "{}",
                }

                def run_job(stage, **extra):
                    queued = client.post(
                        request_path + "/evidence/" + eid + "/analysis",
                        json={
                            "revision": row["revision"],
                            "confirmed": True,
                            "stage": stage,
                            "request_key": "live-" + stage,
                            **extra,
                        },
                    )
                    assert queued.status_code == 202, queued.text
                    body = queued.json()
                    row["revision"] = body["revision"]
                    print("Queued live " + stage + " job", flush=True)
                    start_time = time.monotonic()
                    with (root / (stage + "-worker.log")).open("wb") as output:
                        worker = subprocess.run(
                            [
                                sys.executable,
                                str(ROOT / "scripts/drone_followup_worker.py"),
                                "--kind",
                                "analysis",
                                "--once",
                            ],
                            env=env,
                            cwd=ROOT,
                            stdin=subprocess.DEVNULL,
                            stdout=output,
                            stderr=output,
                            timeout=240,
                        )
                    with factory() as db:
                        saved = db.get(CaseDroneAnalysisRow, body["analysis_id"])
                        value = analysis.out(saved)
                    value["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
                    result["jobs"].append(value)
                    (root / "progress.json").write_text(json.dumps(result, indent=2))
                    assert worker.returncode == 0, "Worker process failed"
                    assert value["status"] == "completed", (
                        "Live " + stage + " failed: " + str(value["error_code"])
                    )
                    assert "fixture" not in str(value["result"].get("model", "")).lower(), (
                        "Fixture model is not a live check"
                    )
                    print("Completed live " + stage + " job", flush=True)
                    return value

                detected = run_job("detect")
                detections = detected["result"]["detections"]
                index = (
                    args.animal_index
                    if args.animal_index is not None
                    else (0 if len(detections) == 1 else None)
                )
                if index is None or not 0 <= index < len(detections):
                    result["status"] = "needs_target_selection"
                    result["target_selection_note"] = (
                        "Choose a target explicitly; absent/multiple targets "
                        "are not resolved silently."
                    )
                    raise SystemExit(2)
                result["selected_animal_index"] = index
                result["target_selection_note"] = (
                    "Sole detector target after source-photo visual inspection."
                    if args.animal_index is None
                    else "Explicitly selected detector target."
                )
                run_job("assess", detection_job_id=detected["analysis_id"], animal_index=index)
                detail = client.get(request_path).json()
                assert len(detail["evidence"]) == 1
                assert detail["evidence"][0]["sha256"] == source["prepared_sha256"]
                assert all(job["requires_human_review"] for job in result["jobs"])
                ready = change(
                    client,
                    row,
                    "evidence_ready",
                    note="Live advisory result is ready for review; "
                    "no operational finding confirmed.",
                )
                assert ready.status_code == 200, ready.text
                with factory() as db:
                    incident = db.get(IncidentRow, "case")
                    current = {
                        "report": incident.report_json,
                        "assessment": incident.assessment_json,
                        "identification": incident.identification_json,
                    }
                    assert current == original, "Original intake changed"
                    assert db.get(NetworkCaseRow, "case").response_phase == original_phase
                    assert db.scalar(select(CaseDroneReminderRow.notification_id)) is None
                    saved = db.get(CaseDroneEvidenceRow, eid)
                    assert saved.metadata_json["captured_at"] is None
                    assert saved.metadata_json.get("animal_latitude") is None
                result["checks"] = {
                    "evidence_hash_matches": True,
                    "real_worker_detection_completed": True,
                    "real_worker_assessment_completed": True,
                    "original_intake_preserved": True,
                    "rescue_phase_preserved": True,
                    "camera_capture_time_retained_unknown": True,
                    "animal_coordinates_retained_unknown": True,
                    "notifications_not_queued": True,
                    "ready_for_coordinator_review": True,
                }
                accepted = result["jobs"][-1]["result"]["assessment"]
                guard = result["jobs"][-1]["result"]["context_validation"]
                grounding_checks = {
                    "environmental_deadline_withheld": accepted["time_sensitivity_hours"]
                    is None,
                    "movement_retained_unknown": accepted["injury"]["mobility_concern"]
                    == "unknown",
                    "unresponsiveness_not_inferred": accepted["injury"]["unresponsive"]
                    is False,
                    "no_unanswerable_reporter_question": accepted["next_question"] is None,
                    "withheld_context_auditable": bool(guard["withheld_model_fields"]),
                }
                assert all(grounding_checks.values()), grounding_checks
                result["checks"].update(grounding_checks)
                result["status"] = "passed"
                result["human_review_performed"] = False
            finally:
                generator.close()
    except Exception as exc:
        result["status"] = "failed"
        result["failure_type"] = type(exc).__name__
        # Keep secret/provider diagnostics out of the user-facing report.
        print(
            "Live pipeline check failed; inspect the protected local worker log.",
            file=sys.stderr,
        )
    finally:
        monkey.undo()
        result["completed_at"] = time.time()
        result["elapsed_seconds"] = round(result["completed_at"] - result["started_at"], 3)
        result["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        code_paths = [
            "scripts/drone_followup_worker.py",
            "backend/lifejacket/services/drone_followup.py",
            "backend/lifejacket/services/drone_frame_analysis.py",
            "backend/lifejacket/services/drone_vision.py",
            "backend/lifejacket/agents/detection.py",
            "backend/lifejacket/agents/identification.py",
            "backend/lifejacket/agents/assessment.py",
            "prompts/identification/detect_animals.md",
            "prompts/identification/identify_species.md",
            "prompts/assessment/assess_situation.md",
        ]
        result["source_code_sha256"] = {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in code_paths
        }
        result["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (root / "result.json").write_text(json.dumps(result, indent=2))
        print("Result: " + result.get("status", "unknown"), flush=True)
    if result.get("status") != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
