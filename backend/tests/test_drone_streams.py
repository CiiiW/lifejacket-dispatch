"""Stream permissions, provenance, expiry and explicit human selection."""

import io
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from lifejacket.access.policy import Role
from lifejacket.api.routes import drone_streams
from lifejacket.config import settings
from lifejacket.models.tables import (
    CaseDroneEvidenceRow,
    CaseDroneStreamRow,
    IncidentRow,
    NetworkCaseRow,
)
from lifejacket.services import drone_requests as requests
from lifejacket.services import drone_streams as streams
from PIL import Image
from sqlalchemy import select
from test_drone_requests import (
    BASE,
    change,
    drone_api,  # noqa: F401
    start,
)
from test_network_actions import (
    actor,
    api,  # noqa: F401
)


@pytest.fixture
def stream_api(drone_api, monkeypatch):  # noqa: F811
    client, factory, current = drone_api
    client.app.include_router(drone_streams.router)
    monkeypatch.setattr(settings, "drone_streams_enabled", True)
    monkeypatch.setattr(settings, "drone_stream_receiver_secret", "x" * 40)
    monkeypatch.setattr(settings, "drone_stream_publish_base", "rtmp://127.0.0.1:19350/live")
    return client, factory, current


def opened(client):
    row = start(client)
    path = BASE + "/" + row["request_id"] + "/streams"
    r = client.post(
        path,
        json={
            "revision": row["revision"],
            "label": "Recorded rehearsal",
            "rights_note": "Synthetic test image only",
            "source_url": "https://example.org/fixture",
        },
    )
    assert r.status_code == 201, r.text
    return row, path, r.json()


def jpeg(color="blue"):
    b = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(b, format="JPEG")
    return b.getvalue()


def test_stream_selected_frame_preserves_provenance_and_enters_review(stream_api):
    client, factory, _ = stream_api
    row, path, grant = opened(client)
    sid = grant["stream_id"]
    listed = client.get(path)
    assert listed.status_code == 200 and "no-store" in listed.headers["cache-control"]
    assert "publish_url" not in listed.text and "token_hash" not in listed.text
    assert client.get(path + "/" + sid + "/preview").json()["status"] == "waiting"
    with factory() as db:
        assert streams.receive(db, sid, jpeg())
    preview = client.get(path + "/" + sid + "/preview").json()
    assert preview["status"] == "connected"
    assert preview["can_manage"] is True
    frame = preview["frame"]
    # A newer frame must not change the explicit frame selection.
    with factory() as db:
        assert streams.receive(db, sid, jpeg("red"))
    captured = client.post(
        path + "/" + sid + "/capture",
        json={
            "revision": grant["revision"],
            "frame_id": frame["frame_id"],
            "description": "Selected view requires coordinator review",
        },
    )
    assert captured.status_code == 201, captured.text
    with factory() as db:
        evidence = db.scalar(select(CaseDroneEvidenceRow))
        assert evidence.sha256 == frame["sha256"]
        assert evidence.metadata_json["source_session_id"] == sid
        assert evidence.metadata_json["captured_at"] is None
        assert evidence.metadata_json["animal_latitude"] is None
        assert evidence.metadata_json["received_at"] == frame["received_at"]
        assert db.get(IncidentRow, "case").report_json == {"secret": "INTERNAL"}
    row["revision"] = captured.json()["revision"]
    ready = change(client, row, "evidence_ready")
    assert ready.status_code == 200, ready.text
    assert (
        change(client, ready.json(), "reviewed", outcome="still_uncertain").status_code == 200
    )
    assert client.get(path + "/" + sid + "/preview").json()["frame"] is None


def test_grants_publish_only_exact_path_and_end_revokes(stream_api):
    client, factory, _ = stream_api
    _, path, grant = opened(client)
    sid = grant["stream_id"]
    token = parse_qs(urlsplit(grant["publish_url"]).query)["pass"][0]
    body = {
        "user": "publisher",
        "password": token,
        "ip": "127.0.0.1",
        "protocol": "rtmp",
        "action": "publish",
        "path": "live/" + sid,
    }
    with factory() as db:
        assert "expireAt" in streams.authorize(db, body)
        for extra in [
            {"action": "read"},
            {"path": "live/" + "0" * 32},
            {"password": "wrong"},
            {"protocol": "rtsp"},
        ]:
            with pytest.raises(HTTPException) as exc:
                streams.authorize(db, {**body, **extra})
            assert exc.value.status_code == 401
        assert streams.receive(db, sid, jpeg())
    end = client.post(path + "/" + sid + "/end", json={"revision": grant["revision"]})
    assert end.status_code == 200, end.text
    assert client.get(path + "/" + sid + "/preview").json()["frame"] is None
    with factory() as db:
        assert not streams.receive(db, sid, jpeg())
        assert db.get(CaseDroneStreamRow, sid).frames_json == []
        with pytest.raises(HTTPException):
            streams.authorize(db, body)


@pytest.mark.parametrize(
    "person", [actor("C"), actor("B"), actor("B", Role.RESCUER, "rescuer")]
)
def test_only_lead_manages_stream_and_nonparticipant_cannot_view(stream_api, person):
    client, _, current = stream_api
    _, path, grant = opened(client)
    current[0] = person
    r = client.get(path)
    assert r.status_code in {200, 403, 404}
    if r.status_code == 200:
        assert not r.json()["streams"][0]["can_manage"]
    assert client.post(
        path + "/" + grant["stream_id"] + "/end", json={"revision": grant["revision"]}
    ).status_code in {403, 404}
    if person.organization_id == "C":
        assert client.get(path + "/" + grant["stream_id"] + "/preview").status_code in {
            403,
            404,
        }


def test_stale_frames_missing_selection_expiry_and_case_change(stream_api):
    client, factory, _ = stream_api
    _, path, grant = opened(client)
    sid = grant["stream_id"]
    with factory() as db:
        streams.receive(db, sid, jpeg())
        row = db.get(CaseDroneStreamRow, sid)
        frames = [dict(row.frames_json[0])]
        frames[0]["received_at"] = (requests.now() - timedelta(seconds=20)).isoformat() + "Z"
        row.frames_json = frames
        db.commit()
    assert client.get(path + "/" + sid + "/preview").json()["status"] == "interrupted"
    assert client.get(path + "/" + sid + "/preview").json()["frame"] is None
    assert (
        client.post(
            path + "/" + sid + "/capture",
            json={
                "revision": grant["revision"],
                "frame_id": frames[0]["frame_id"],
                "description": "Expired",
            },
        ).status_code
        == 409
    )
    with factory() as db:
        row = db.get(CaseDroneStreamRow, sid)
        row.expires_at = requests.now() - timedelta(seconds=1)
        db.commit()
    assert client.get(path + "/" + sid + "/preview").json()["status"] == "expired"
    with factory() as db:
        row = db.get(CaseDroneStreamRow, sid)
        row.expires_at = requests.now() + timedelta(minutes=1)
        db.get(NetworkCaseRow, "case").lead_org_id = "B"
        db.commit()
    assert client.get(path + "/" + sid + "/preview").status_code in {403, 404}


def test_one_session_revision_source_and_flags(stream_api, monkeypatch):
    client, _, _ = stream_api
    _, path, grant = opened(client)
    body = {
        "revision": grant["revision"],
        "label": "Second",
        "rights_note": "Synthetic",
        "source_url": "https://example.org/fixture",
    }
    assert client.post(path, json=body).status_code == 409
    assert (
        client.post(path + "/" + grant["stream_id"] + "/end", json={"revision": 0}).status_code
        == 409
    )
    monkeypatch.setattr(settings, "drone_streams_enabled", False)
    assert client.get(path).status_code == 503
