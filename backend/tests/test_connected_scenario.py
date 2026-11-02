import json
import os
import subprocess
import sys
from pathlib import Path


def test_connected_scenario_is_disposable_and_uses_one_case_across_roles(tmp_path):
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "artifacts"
    sentinel = tmp_path / "never-use-this.sqlite"
    sentinel.write_bytes(b"DO NOT MODIFY")
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///" + sentinel.as_posix()
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/run_connected_scenario.py"),
            "--output-dir",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert sentinel.read_bytes() == b"DO NOT MODIFY"
    report = json.loads((output / "latest.json").read_text())
    assert report["passed"] and report["temporary_database_removed"]
    assert len(report["checks"]) >= 35
    assert all(step["passed"] for step in report["checks"])
    assert {step["role"] for step in report["checks"]} >= {
        "reporter",
        "a",
        "b",
        "rescuer-b",
        "noaa",
    }
    assert [step["phase"] for step in report["reporter_timeline"]] == [
        "received",
        "accepted",
        "en_route",
        "on_scene",
        "animal_located",
        "closed",
    ]
    data = (output / "latest.json").read_text()
    assert "draft_key" not in data and "id_token" not in data and "+12025550123" not in data
    assert "One case, connected across roles" in (output / "latest.html").read_text()
