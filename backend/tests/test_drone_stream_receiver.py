"""Opt-in real RTMP transport test with a generated video and disposable case."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_drone_requests import drone_api  # noqa: F401
from test_drone_streams import (
    opened,
    stream_api,  # noqa: F401
)
from test_network_actions import api  # noqa: F401


def wait_until(fn, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError("Timed out waiting for media pipeline")


def test_recorded_rtmp_to_case_evidence_and_disconnect(stream_api, tmp_path):  # noqa: F811
    media = os.environ.get("MEDIAMTX_BINARY")
    ffmpeg = os.environ.get("FFMPEG_BINARY", "ffmpeg")
    if not media:
        pytest.skip("Set MEDIAMTX_BINARY for actual RTMP rehearsal")
    client, factory, _ = stream_api
    row, path, grant = opened(client)
    root = Path(__file__).resolve().parents[2]
    video = tmp_path / "synthetic-rehearsal.mp4"
    generated = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=15",
            "-t",
            "15",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "15",
            str(video),
        ],
        capture_output=True,
        timeout=30,
    )
    assert generated.returncode == 0
    env = {
        **os.environ,
        "DATABASE_URL": str(factory.kw["bind"].url),
        "NETWORK_AUTH_ENABLED": "true",
        "CASE_DRONE_REQUESTS_ENABLED": "true",
        "DRONE_STREAMS_ENABLED": "true",
        "DRONE_RECORDINGS_ENABLED": "true",
        "DRONE_EVIDENCE_DIR": str(tmp_path / "recorded-evidence"),
        "DRONE_STREAM_RECEIVER_SECRET": "x" * 40,
    }
    log = open(tmp_path / "receiver.log", "wb")  # noqa: SIM115

    def start_receiver():
        return subprocess.Popen(
            [
                sys.executable,
                str(root / "scripts/drone_stream_receiver.py"),
                "--mediamtx",
                media,
                "--ffmpeg",
                ffmpeg,
            ],
            env=env,
            cwd=root,
            stdout=log,
            stderr=log,
        )

    receiver = start_receiver()
    publishers = []
    endpoint = path + "/" + grant["stream_id"]

    def publish(url):
        p = subprocess.Popen(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-i",
                str(video),
                "-c",
                "copy",
                "-an",
                "-f",
                "flv",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        publishers.append(p)
        return p

    try:
        from urllib.request import urlopen

        def healthy():
            if receiver.poll() is not None:
                raise AssertionError("Receiver stopped")
            try:
                with urlopen("http://127.0.0.1:18941/health", timeout=1) as r:
                    return r.status == 200
            except OSError:
                return False

        wait_until(healthy)
        import socket

        def rtmp_ready():
            if receiver.poll() is not None:
                raise AssertionError("Receiver stopped")
            try:
                with socket.create_connection(("127.0.0.1", 19350), timeout=0.5):
                    return True
            except OSError:
                return False

        wait_until(rtmp_ready)
        # A wrong publish credential cannot create a preview.
        bad = publish(grant["publish_url"] + "wrong")
        wait_until(lambda: bad.poll() is not None)
        assert bad.returncode != 0
        assert client.get(endpoint + "/preview").json()["frame"] is None
        good = publish(grant["publish_url"])
        view = wait_until(
            lambda: (
                v if (v := client.get(endpoint + "/preview").json()).get("frame") else None
            ),
            30,
        )
        assert view["status"] == "connected"
        frame = view["frame"]
        saved = client.post(
            endpoint + "/capture",
            json={
                "revision": grant["revision"],
                "frame_id": frame["frame_id"],
                "description": "Synthetic recorded-stream rehearsal, not animal validation",
            },
        )
        assert saved.status_code == 201, saved.text
        good.terminate()
        good.wait(timeout=5)
        stale = wait_until(
            lambda: (
                v
                if (v := client.get(endpoint + "/preview").json())["status"] == "interrupted"
                else None
            ),
            15,
        )
        assert stale["frame"] is None
        # Closed segments are persistent and only available through case authorization.
        from lifejacket.config import settings

        old_directory = settings.drone_evidence_dir
        settings.drone_evidence_dir = tmp_path / "recorded-evidence"
        try:

            def recorded():
                archive = client.get(endpoint + "/recordings").json()
                return archive if any(r["segments"] for r in archive["recordings"]) else None

            archive = wait_until(recorded, 20)
            recording = next(r for r in archive["recordings"] if r["segments"])
            segment = recording["segments"][0]
            video_path = (
                endpoint
                + "/recordings/"
                + recording["recording_id"]
                + "/"
                + segment["segment_id"]
            )
            playback = client.get(video_path)
            assert playback.status_code == 200, playback.text
            assert playback.headers["content-type"] == "video/mp4"
            import hashlib

            assert hashlib.sha256(playback.content).hexdigest() == segment["sha256"]
        finally:
            settings.drone_evidence_dir = old_directory
        # Restart the actual receiver on the same ports/lock, preserving the grant
        # and saved evidence in the shared database.
        receiver.terminate()
        receiver.wait(timeout=5)
        assert client.get(BASE_PHOTO(row, saved)).status_code == 200
        receiver = start_receiver()
        wait_until(healthy)
        wait_until(rtmp_ready)
        again = publish(grant["publish_url"])
        wait_until(lambda: client.get(endpoint + "/preview").json().get("frame"), 30)
        ended = client.post(endpoint + "/end", json={"revision": saved.json()["revision"]})
        assert ended.status_code == 200, ended.text
        assert client.get(endpoint + "/preview").json()["frame"] is None
        wait_until(lambda: again.poll() is not None, 15)
        assert client.get(BASE_PHOTO(row, saved)).status_code == 200
    finally:
        for p in publishers:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=5)
        receiver.terminate()
        try:
            receiver.wait(timeout=5)
        except subprocess.TimeoutExpired:
            receiver.kill()
            receiver.wait()
        log.close()


def BASE_PHOTO(row, saved):
    return (
        "/network/cases/case/drone-requests/"
        + row["request_id"]
        + "/evidence/"
        + saved.json()["evidence_id"]
        + "/photo"
    )
