"""Execute the connected drone scenario in its isolated subprocess."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def test_connected_drone_workflow_uses_real_routes_and_preserves_isolation(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "results"
    database = tmp_path / "inherited.sqlite"
    database.write_bytes(b"DO NOT MODIFY")
    evidence = tmp_path / "inherited-evidence"
    evidence.mkdir()
    (evidence / "sentinel").write_bytes(b"DO NOT MODIFY")
    env = os.environ.copy()
    env.update(
        DATABASE_URL="sqlite:///" + database.as_posix(),
        DRONE_EVIDENCE_DIR=str(evidence),
        DRONE_VERIFICATION_CONFIDENCE_THRESHOLD="0.10",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/run_connected_scenario.py"),
            "--with-drone",
            "--output-dir",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert database.read_bytes() == b"DO NOT MODIFY"
    assert sorted(p.name for p in evidence.iterdir()) == ["sentinel"]
    assert (evidence / "sentinel").read_bytes() == b"DO NOT MODIFY"
    report = json.loads((output / "latest.json").read_text())
    assert report["passed"] and report["temporary_database_removed"]
    assert report["mode"] == "isolated-connected-drone-scenario"
    assert len(report["checks"]) >= 65 and all(r["passed"] for r in report["checks"])
    workflow = report["drone_workflow"]
    assert workflow["case_reference"] == "CASE-01"
    assert workflow["request_reference"] == "DRONE-01"
    assert workflow["same_case_verified"] and workflow["original_intake_preserved"]
    assert workflow["rescue_phase_preserved_during_drone_review"] == "received"
    assert workflow["operational_suggestion_preserved"]
    assert workflow["status"] == "reviewed" and workflow["outcome"] == "still_uncertain"
    assert workflow["execution_kind"] == "recorded_demo" and workflow["source_is_synthetic"]
    assert workflow["capture_time"] is None and workflow["animal_coordinates"] is None
    assert workflow["threshold"] == 0.90
    assert workflow["initial_confidence"] == {"animal_group": 0.62, "condition": 0.58}
    assert [r["event"] for r in workflow["timeline"]] == [
        "requested",
        "approved",
        "in_progress",
        "evidence_attached",
        "evidence_ready",
        "reviewed",
    ]
    assert [r["revision"] for r in workflow["timeline"]] == list(range(6))
    frame = base64.b64decode(workflow["frame_base64"])
    assert hashlib.sha256(frame).hexdigest() == workflow["evidence_sha256"]
    assert frame.startswith(b"\x89PNG")
    assert [r["phase"] for r in report["reporter_timeline"]] == [
        "received",
        "accepted",
        "en_route",
        "on_scene",
        "animal_located",
        "closed",
    ]
    exported = (output / "latest.json").read_text()
    for secret in ["draft_key", "id_token", "+12025550123", "scenario-reporter"]:
        assert secret not in exported
    page = (output / "latest.html").read_text()
    assert page == (output / "index.html").read_text()
    assert 'src="data:image/png;base64,' in page
    assert "One reported case. One reviewed drone request." in page
    assert "Sample review leaves the operational suggestion available" in page
