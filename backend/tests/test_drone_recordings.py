"""Recording authorization, bounded private retrieval and integrity."""

import hashlib
from datetime import timedelta

from lifejacket.config import settings
from lifejacket.models.tables import CaseDroneRecordingRow
from lifejacket.services import drone_recordings as recordings
from lifejacket.services import drone_requests as requests
from test_drone_requests import drone_api  # noqa: F401
from test_drone_streams import opened, stream_api  # noqa: F401
from test_network_actions import actor, api  # noqa: F401


def archived(context, monkeypatch, tmp_path):
    client, factory, _ = context
    monkeypatch.setattr(settings, "drone_evidence_dir", tmp_path / "evidence")
    _, path, grant = opened(client)
    rid = "a" * 32
    directory = recordings.root() / rid
    directory.mkdir(parents=True)
    data = b"private-test-video"
    (directory / "000000.mp4").write_bytes(data)
    with factory() as db:
        db.add(
            CaseDroneRecordingRow(
                recording_id=rid,
                stream_id=grant["stream_id"],
                status="complete",
                started_at=requests.now(),
                updated_at=requests.now(),
                segments_json=[
                    {
                        "segment_id": "000000",
                        "offset_seconds": 0,
                        "duration_seconds": 5,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                ],
            )
        )
        db.commit()
    base = path + "/" + grant["stream_id"]
    return base, rid, grant


def test_recordings_remain_private_after_session_end(stream_api, monkeypatch, tmp_path):  # noqa: F811
    client, _, current = stream_api
    base, rid, grant = archived(stream_api, monkeypatch, tmp_path)
    video = base + "/recordings/" + rid + "/000000"
    assert client.get(base + "/recordings").json()["recordings"][0]["status"] == "complete"
    response = client.get(video)
    assert response.content == b"private-test-video"
    assert "no-store" in response.headers["cache-control"]
    assert client.post(base + "/end", json={"revision": grant["revision"]}).status_code == 200
    assert client.get(video).status_code == 200
    current[0] = actor("unrelated")
    assert client.get(video).status_code in {403, 404}
    assert client.get(base + "/recordings").status_code in {403, 404}


def test_segment_scope_tampering_and_stale_worker(stream_api, monkeypatch, tmp_path):  # noqa: F811
    client, factory, _ = stream_api
    base, rid, _ = archived(stream_api, monkeypatch, tmp_path)
    assert client.get(base + "/recordings/" + "b" * 32 + "/000000").status_code == 404
    assert client.get(base + "/recordings/" + rid + "/not-a-segment").status_code == 404
    (recordings.root() / rid / "000000.mp4").write_bytes(b"altered-test-video")
    assert client.get(base + "/recordings/" + rid + "/000000").status_code == 409
    with factory() as db:
        row = db.get(CaseDroneRecordingRow, rid)
        row.status = "recording"
        row.updated_at = requests.now() - timedelta(seconds=30)
        db.commit()
    result = client.get(base + "/recordings").json()
    assert result["recordings"][0]["status"] == "interrupted"


def test_recording_limit_and_start_failure_are_persisted(stream_api, monkeypatch, tmp_path):  # noqa: F811
    import pytest

    _, factory, _ = stream_api
    _, _, grant = archived(stream_api, monkeypatch, tmp_path)
    monkeypatch.setattr(recordings, "MAX_SESSION_BYTES", 0)
    with pytest.raises(OSError):
        recordings.Recorder(factory, grant["stream_id"], "unused", "/no-such-ffmpeg")
    with factory() as db:
        result = recordings.listing(db, grant["stream_id"])["recordings"]
    assert any(r["status"] == "limited" and r["error_code"] == "storage_limit" for r in result)
    monkeypatch.setattr(recordings, "MAX_SESSION_BYTES", 512 * 1024 * 1024)
    with pytest.raises(OSError):
        recordings.Recorder(factory, grant["stream_id"], "unused", "/no-such-ffmpeg")
    with factory() as db:
        result = recordings.listing(db, grant["stream_id"])["recordings"]
    assert any(
        r["status"] == "failed" and r["error_code"] == "recorder_start_failed" for r in result
    )
