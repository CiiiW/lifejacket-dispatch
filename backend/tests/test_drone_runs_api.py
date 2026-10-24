import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.api.routes.drones import router
from lifejacket.config import settings
from lifejacket.drones.runs import save_run


def test_run_list_and_detail_are_read_only_and_reject_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "drone_runs_dir", tmp_path)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    run = {
        "run_id": uuid.uuid4().hex,
        "status": "completed",
        "plan": {},
        "samples": [{"latitude": 36.8}],
        "events": [],
    }
    save_run(tmp_path, run)
    assert "samples" not in client.get("/drones/runs").json()[0]
    assert client.get(f"/drones/runs/{run['run_id']}").json()["samples"] == run["samples"]
    assert client.get("/drones/runs/invalid").status_code == 422
    assert client.get(f"/drones/runs/{uuid.uuid4().hex}").status_code == 404
    assert client.post(f"/drones/runs/{run['run_id']}").status_code == 405
