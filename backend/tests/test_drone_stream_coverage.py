"""Readiness audit: revocation, failure paths, bounded storage and bad inputs."""
# ruff: noqa: F811 -- imported pytest fixtures are resolved by parameter name.

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from lifejacket.models.tables import (
    CaseDroneEvidenceRow,
    CaseDroneRequestRow,
    CaseDroneStreamRow,
    IncidentRow,
    NetworkCaseRow,
)
from lifejacket.services import drone_requests as requests
from lifejacket.services import drone_streams as streams
from sqlalchemy import select
from test_drone_requests import drone_api  # noqa: F401
from test_drone_streams import (
    jpeg,
    opened,
    stream_api,  # noqa: F401
)
from test_network_actions import api  # noqa: F401


def publisher(grant):
    return {
        "user": "publisher",
        "password": parse_qs(urlsplit(grant["publish_url"]).query)["pass"][0],
        "ip": "127.0.0.1",
        "protocol": "rtmp",
        "action": "publish",
        "path": "live/" + grant["stream_id"],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("submitted", False),
        ("verified_at", None),
        ("verified_by", None),
        ("verified_by", "  "),
        ("state_code", None),
        ("state_code", "ZZ"),
    ],
)
def test_scope_revocation_stops_publish_and_collection(stream_api, field, value):
    client, factory, _ = stream_api
    _, path, grant = opened(client)
    with factory() as db:
        assert streams.receive(db, grant["stream_id"], jpeg())
        setattr(db.get(NetworkCaseRow, "case"), field, value)
        db.commit()
        row = db.get(CaseDroneStreamRow, grant["stream_id"])
        assert not streams.active(db, row)
        assert not streams.receive(db, grant["stream_id"], jpeg())
        with pytest.raises(HTTPException) as exc:
            streams.authorize(db, publisher(grant))
        assert exc.value.status_code == 401
    assert client.get(path + "/" + grant["stream_id"] + "/preview").status_code in {
        403,
        404,
        409,
    }


@pytest.mark.parametrize(
    ("table", "field", "value"),
    [
        (CaseDroneRequestRow, "status", "failed"),
        (CaseDroneRequestRow, "status", "cancelled"),
        (CaseDroneRequestRow, "status", "evidence_ready"),
        (CaseDroneRequestRow, "status", "reviewed"),
        (NetworkCaseRow, "response_phase", "closed"),
        (NetworkCaseRow, "lead_org_id", "B"),
        (IncidentRow, "status", "resolved"),
        (IncidentRow, "status", "cancelled"),
        (IncidentRow, "status", "duplicate"),
    ],
)
def test_case_and_request_endings_revoke_existing_grant(stream_api, table, field, value):
    client, factory, _ = stream_api
    row, path, grant = opened(client)
    with factory() as db:
        target = db.get(table, row["request_id"] if table is CaseDroneRequestRow else "case")
        setattr(target, field, value)
        db.commit()
        assert not streams.receive(db, grant["stream_id"], jpeg())
        with pytest.raises(HTTPException) as exc:
            streams.authorize(db, publisher(grant))
        assert exc.value.status_code == 401


def test_preview_buffer_is_bounded_and_stale_capture_is_transactional(stream_api):
    client, factory, _ = stream_api
    _, path, grant = opened(client)
    sid = grant["stream_id"]
    with factory() as db:
        for _ in range(25):
            assert streams.receive(db, sid, jpeg())
        row = db.get(CaseDroneStreamRow, sid)
        db.refresh(row)
        assert len(row.frames_json) == streams.MAX_FRAMES
        frame = row.frames_json[-1]
    r = client.post(
        path + "/" + sid + "/capture",
        json={"revision": 0, "frame_id": frame["frame_id"], "description": "Stale editor"},
    )
    assert r.status_code == 409
    with factory() as db:
        assert db.scalar(select(CaseDroneEvidenceRow.evidence_id)) is None
    with factory() as db:
        row = db.get(CaseDroneStreamRow, sid)
        row.expires_at = requests.now() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException):
            streams.authorize(db, publisher(grant))
        assert not streams.receive(db, sid, jpeg())


@pytest.mark.parametrize("bad", [b"not a JPEG", b"X" * (256 * 1024 + 1)])
def test_invalid_frames_do_not_replace_good_preview(stream_api, bad):
    client, factory, _ = stream_api
    _, _, grant = opened(client)
    with factory() as db:
        streams.receive(db, grant["stream_id"], jpeg())
        row = db.get(CaseDroneStreamRow, grant["stream_id"])
        db.refresh(row)
        before = row.frames_json[-1]["frame_id"]
        with pytest.raises((ValueError, OSError)):
            streams.receive(db, grant["stream_id"], bad)
        db.refresh(row)
        assert row.frames_json[-1]["frame_id"] == before


@pytest.mark.parametrize("url", ["https://[broken", "http://example.org/video"])
def test_bad_recording_references_are_validation_errors(stream_api, url):
    from test_drone_requests import BASE, start

    client, _, _ = stream_api
    row = start(client)
    r = client.post(
        BASE + "/" + row["request_id"] + "/streams",
        json={
            "revision": row["revision"],
            "label": "Rehearsal",
            "rights_note": "Synthetic",
            "source_url": url,
        },
    )
    assert r.status_code == 422
