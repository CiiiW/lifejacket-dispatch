# ruff: noqa: E402
"""Private connected rehearsal using ONLY disposable fixture data and identity.

Requires development/test dependencies. Never mount in the production app.
"""

import argparse
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
from lifejacket.config import settings  # noqa: E402
from lifejacket.models.tables import CaseDroneRequestRow  # noqa: E402
from lifejacket.services import (
    drone_frame_analysis as frame_ai,
)  # noqa: E402
from lifejacket.services import (
    drone_reminders,
    drone_requests,
)
from test_drone_followup import followup_api  # noqa: E402
from test_drone_requests import drone_api  # noqa: E402
from test_drone_streams import opened, stream_api  # noqa: E402
from test_network_actions import api  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mediamtx", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--port", type=int, default=8935)
    args = parser.parse_args()
    children = []
    monkey = pytest.MonkeyPatch()
    followup_stop = threading.Event()
    followup_thread = None
    with tempfile.TemporaryDirectory(prefix="lifejacket-stream-demo-") as temp:
        directory = Path(temp)
        generator = api.__wrapped__(directory, monkey)
        current = next(generator)
        try:
            drone = drone_api.__wrapped__(current, monkey, directory)
            stream_context = stream_api.__wrapped__(drone, monkey)
            client, factory, _ = followup_api.__wrapped__(stream_context, monkey)
            monkey.setattr(settings, "drone_stream_receiver_secret", secrets.token_urlsafe(32))
            monkey.setattr(settings, "drone_recordings_enabled", True)
            demo_row, _, grant = opened(client)
            with factory() as db:
                request = db.get(CaseDroneRequestRow, demo_row["request_id"])
                request.payload_json = {
                    **request.payload_json,
                    "next_review_at": (drone_requests.now() - timedelta(hours=1)).isoformat()
                    + "Z",
                }
                db.commit()

            def synthetic_analysis(db, job):
                if job.input_json["stage"] == "detect":
                    return {
                        "detections": [
                            {
                                "box": [0, 0, 1000, 1000],
                                "description": "Synthetic test pattern, not an animal",
                                "kind": "other",
                            }
                        ],
                        "limitations": ["Fixture result only; no wildlife model was called."],
                        "model": "synthetic-fixture",
                    }
                return {
                    "identity_summary": {
                        "name": "Generated test pattern (demo)",
                        "confidence": 0.0,
                    },
                    "assessment": {
                        "injury": {
                            "summary": "Synthetic footage cannot establish animal condition."
                        },
                        "severity_level": "unknown",
                        "requires_human_review": True,
                    },
                    "limitations": ["Fixture result only; no wildlife model was called."],
                    "model": "synthetic-fixture",
                }

            def local_delivery(_url, body, _headers):
                with (directory / "captured-reminders.jsonl").open("ab") as output:
                    output.write(body + b"\n")

            def followup_work():
                while not followup_stop.is_set():
                    frame_ai.process_one(factory, synthetic_analysis)
                    drone_reminders.deliver_one(factory, local_delivery)
                    followup_stop.wait(1)

            followup_thread = threading.Thread(target=followup_work, daemon=True)
            followup_thread.start()
            video = directory / "synthetic.mp4"
            subprocess.run(
                [
                    args.ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=640x360:rate=15",
                    "-t",
                    "30",
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
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            env = {
                **os.environ,
                "DATABASE_URL": str(factory.kw["bind"].url),
                "NETWORK_AUTH_ENABLED": "true",
                "CASE_DRONE_REQUESTS_ENABLED": "true",
                "DRONE_STREAMS_ENABLED": "true",
                "DRONE_RECORDINGS_ENABLED": "true",
                "DRONE_EVIDENCE_DIR": str(settings.drone_evidence_dir),
                "DRONE_STREAM_RECEIVER_SECRET": settings.drone_stream_receiver_secret,
            }
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "scripts/drone_stream_receiver.py"),
                        "--mediamtx",
                        args.mediamtx,
                        "--ffmpeg",
                        args.ffmpeg,
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            import socket

            deadline = time.monotonic() + 20
            while True:
                if children[0].poll() is not None:
                    raise RuntimeError("Private receiver stopped during startup")
                try:
                    with socket.create_connection(("127.0.0.1", 19350), timeout=0.5):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Private media receiver did not start") from None
                    time.sleep(0.25)
            children.append(
                subprocess.Popen(
                    [
                        args.ffmpeg,
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-stream_loop",
                        "-1",
                        "-re",
                        "-i",
                        str(video),
                        "-c",
                        "copy",
                        "-an",
                        "-f",
                        "flv",
                        grant["publish_url"],
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

            async def api_proxy(scope, receive, send):
                scope = dict(scope)
                prefix = scope.get("root_path", "")
                scope["path"] = scope["path"][len(prefix) :] or "/"
                scope["root_path"] = ""
                await client.app(scope, receive, send)

            app.mount("/api", api_proxy)
            app.mount("/", StaticFiles(directory=ROOT / "var/drone-stream-preview", html=True))
            uvicorn.run(
                app, host="127.0.0.1", port=args.port, access_log=False, log_level="error"
            )
        finally:
            followup_stop.set()
            if followup_thread:
                followup_thread.join(timeout=3)
            for child in reversed(children):
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            generator.close()
            monkey.undo()


if __name__ == "__main__":
    import contextlib
    import signal

    def shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    with contextlib.suppress(KeyboardInterrupt):
        main()
