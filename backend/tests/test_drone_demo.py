import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lifejacket.api.routes.drone_demo import router
from lifejacket.api.routes.drone_intake import router as real_router
from lifejacket.config import settings
from lifejacket.drones.video import VideoMetadata, digest, prepare_video
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    AssignmentRow,
    Base,
    DroneDemoFrameRow,
    DroneObservationRow,
    IncidentRow,
)
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)
    app.include_router(real_router)

    def sessions():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    monkeypatch.setattr(settings, "drone_demo_enabled", True)
    monkeypatch.setattr(settings, "drone_demo_dir", tmp_path / "evidence")
    with TestClient(app) as client:
        yield client, factory


def frame():
    image = io.BytesIO()
    Image.new("RGB", (16, 12)).save(image, format="JPEG")
    return image.getvalue()


def upload(client, **changes):
    data = frame()
    metadata = dict(
        evidence_kind="toy_demo",
        source="Team-owned toy clip in Chicago",
        rights_note="Team-owned",
        source_sha256="a" * 64,
        frame_sha256=hashlib.sha256(data).hexdigest(),
        offset_seconds=1.5,
        captured_at=None,
    )
    metadata.update(changes)
    return client.post(
        "/drone-demo/frames",
        data={"metadata": json.dumps(metadata)},
        files={"photo": ("frame.jpg", data, "image/jpeg")},
    )


def test_isolation_idempotency_and_no_location_fabrication(api):
    client, factory = api
    row = upload(client).json()
    assert row["demo_only"] is True
    assert row["demo_id"].startswith("demo_")
    assert row["aircraft_position"] is None and row["animal_position"] is None
    assert row["incident_id"] is None
    assert client.get(row["photo_url"]).content == frame()
    assert upload(client).json()["demo_id"] == row["demo_id"]
    for action in ["case", "handoffs", "detect", "analyze"]:
        assert (
            client.post(f"/drone-demo/frames/{row['demo_id']}/{action}", json={}).status_code
            == 404
        )
    # A demo ID cannot be used through the existing real-case handoff path.
    response = client.post(
        f"/drone-intake/observations/{row['demo_id']}/case",
        json={"expected_revision": 0, "actor": "Reviewer"},
    )
    assert response.status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DroneDemoFrameRow)) == 1
        for table in [IncidentRow, DroneObservationRow, AssignmentRow]:
            assert session.scalar(select(func.count()).select_from(table)) == 0


def test_audit_stale_review_and_reimport_cannot_reset_review(api):
    client, _ = api
    row = upload(client).json()
    path = f"/drone-demo/frames/{row['demo_id']}/review"
    body = dict(expected_revision=0, actor="Charlotte", decision="kept", note="Toy visible")
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert response.json()["reviews"][0]["note"] == "Toy visible"
    assert response.json()["revision"] == 1
    assert client.post(path, json=body).status_code == 409
    assert upload(client).json()["status"] == "kept"
    body.update(expected_revision=1, decision="rejected", note="Correcting my review")
    assert len(client.post(path, json=body).json()["reviews"]) == 2
    assert upload(client, source="Different source").status_code == 409
    assert client.post(path, json=body | {"note": " "}).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_kind": "real"},
        {"evidence_kind": "wildlife_recording"},
        {"frame_sha256": "b" * 64},
        {"offset_seconds": float("inf")},
        {"captured_at": "2026-10-31T12:00:00"},
        {"source": " "},
        {"incident_id": "real-case"},
        {"latitude": 41.8, "longitude": -87.6},
        {"detection_status": "completed"},
        {"detection": {"animals": []}},
    ],
)
def test_reject_invalid_or_non_demo_evidence(api, changes):
    client, _ = api
    assert upload(client, **changes).status_code == 422
    assert client.get("/drone-demo/frames").json() == []


def test_disabled_by_default_and_integrity_failure(api, monkeypatch):
    client, factory = api
    row = upload(client).json()
    with factory() as session:
        db_row = session.get(DroneDemoFrameRow, row["demo_id"])
        Path(db_row.storage_path).write_bytes(b"changed")
    assert client.get(row["photo_url"]).status_code == 409
    monkeypatch.setattr(settings, "drone_demo_enabled", False)
    assert client.get("/drone-demo/frames").status_code == 404
    assert upload(client).status_code == 404


def test_importer_preflights_all_frames_and_retries_safely(api, tmp_path):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    source = tmp_path / "toy.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=100x80:rate=5",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
    )
    bundle = tmp_path / "bundle"
    prepare_video(
        source,
        bundle,
        VideoMetadata(evidence_kind="toy_demo", source="Test", rights_note="Generated"),
        max_frames=2,
        interval=1,
    )
    spec = importlib.util.spec_from_file_location(
        "demo_importer", Path(__file__).resolve().parents[2] / "scripts/import_drone_demo.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client, _ = api
    ids = module.import_bundle(bundle, "http://localhost", client=client)
    assert len(ids) == 2
    assert module.import_bundle(bundle, "http://localhost", client=client) == ids
    assert len(client.get("/drone-demo/frames").json()) == 2
    (bundle / "source.mp4").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Original video integrity"):
        module.import_bundle(bundle, "http://localhost", client=client)
    with pytest.raises(ValueError, match="loopback"):
        module.import_bundle(bundle, "https://example.com", client=client)
    assert digest(bundle / "manifest.json")


def test_group_api_complete_source_snapshot_and_review_invalidation(api, monkeypatch):
    client, factory = api
    candidate = {"box": [100, 100, 300, 300], "description": "Scripted", "kind": "seal"}
    for offset in range(3):
        assert (
            upload(
                client,
                offset_seconds=offset,
                detection_status="completed",
                detection={"animals": [candidate]},
            ).status_code
            == 200
        )
    upload(client, source_sha256="b" * 64)
    upload(client, evidence_kind="synthetic_test")
    params = {"source_sha256": "a" * 64, "evidence_kind": "toy_demo"}
    result = client.get("/drone-demo/groups", params=params)
    assert result.status_code == 200
    body = result.json()
    assert body["frame_count"] == 3 and len(body["frames"]) == 3
    assert len(body["groups"]) == 1
    last = body["groups"][0]["members"][-1]
    client.post(
        f"/drone-demo/frames/{last['demo_id']}/review",
        json={
            "expected_revision": 0,
            "actor": "Tester",
            "decision": "rejected",
            "note": "Exclude",
        },
    )
    refreshed = client.get("/drone-demo/groups", params=params).json()
    assert refreshed["excluded_rejected_frames"] == 1
    assert len(refreshed["groups"][0]["members"]) == 2
    assert (
        client.get(
            "/drone-demo/groups", params=params | {"source_sha256": "c" * 64}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/drone-demo/groups", params=params | {"evidence_kind": "wildlife_recording"}
        ).status_code
        == 422
    )
    with factory() as session:
        for table in [IncidentRow, DroneObservationRow, AssignmentRow]:
            assert session.scalar(select(func.count()).select_from(table)) == 0
    monkeypatch.setattr(settings, "drone_demo_enabled", False)
    assert client.get("/drone-demo/groups", params=params).status_code == 404


def test_group_api_refuses_partial_oversized_source(api):
    client, _ = api
    for offset in range(61):
        assert upload(client, offset_seconds=offset).status_code == 200
    response = client.get(
        "/drone-demo/groups", params={"source_sha256": "a" * 64, "evidence_kind": "toy_demo"}
    )
    assert response.status_code == 422


def test_generated_rectangle_clip_import_and_groups_end_to_end(api, tmp_path):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    scripts = Path(__file__).resolve().parents[2] / "scripts"

    def module(name):
        spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result

    bundle = tmp_path / "rectangles"
    manifest = module("make_drone_grouping_fixture").make_fixture(bundle)
    assert len(manifest["frames"]) == 6
    assert manifest["metadata"]["evidence_kind"] == "synthetic_test"
    client, _ = api
    importer = module("import_drone_demo")
    ids = importer.import_bundle(bundle, "http://localhost", client=client)
    assert len(ids) == 6
    result = client.get(
        "/drone-demo/groups",
        params={
            "source_sha256": manifest["source"]["sha256"],
            "evidence_kind": "synthetic_test",
        },
    ).json()
    assert [len(g["members"]) for g in result["groups"]] == [5, 2]
    assert result["warnings"] == []
    assert all(
        f["metadata"]["detector_model"] == "scripted-fixture-not-ai" for f in result["frames"]
    )
    assert importer.import_bundle(bundle, "http://localhost", client=client) == ids
    with pytest.raises(ValueError, match="already exists"):
        module("make_drone_grouping_fixture").make_fixture(bundle)
