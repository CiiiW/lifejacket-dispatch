#!/usr/bin/env python3
"""Private MediaMTX + bounded JPEG collector. Run one receiver per database.

No flight commands. No full-video recording. Binds loopback by default.
"""

import argparse
import base64
import json
import os
import selectors
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import contextlib

import uvicorn
from fastapi import FastAPI, HTTPException
from lifejacket.config import settings
from lifejacket.models.db import SessionLocal, init_db
from lifejacket.models.tables import CaseDroneStreamRow
from lifejacket.services import drone_streams as streams
from sqlalchemy import select


def auth_app():
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/auth")
    def auth(body: dict):
        with SessionLocal() as db:
            return streams.authorize(db, body)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def control(path, method="GET"):
    credential = base64.b64encode(
        ("receiver:" + settings.drone_stream_receiver_secret).encode()
    ).decode()
    request = Request(
        "http://127.0.0.1:19997/v3/" + path,
        method=method,
        headers={"Authorization": "Basic " + credential},
    )
    with urlopen(request, timeout=2) as result:
        return json.load(result) if method == "GET" else None


def run(args):
    streams.enabled()
    init_db()
    # OS lock prevents two collectors from racing over the same frame buffer.
    import fcntl

    lock = open(Path(tempfile.gettempdir()) / "lifejacket-drone-receiver.lock", "w")  # noqa: SIM115
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    app = auth_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=18941, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    config = {
        "logLevel": "error",
        "authMethod": "http",
        "authHTTPAddress": "http://127.0.0.1:18941/auth",
        "authHTTPExclude": [],
        "api": True,
        "apiAddress": "127.0.0.1:19997",
        "rtmp": True,
        "rtmpAddress": args.bind + ":19350",
        "rtsp": True,
        "rtspAddress": "127.0.0.1:18554",
        "rtspTransports": ["tcp"],
        "hls": False,
        "webrtc": False,
        "srt": False,
        "moq": False,
        "pathDefaults": {"overridePublisher": False, "maxReaders": 1, "record": False},
        "paths": {"~^live/[a-f0-9]{32}$": {"source": "publisher"}},
    }
    children = {}
    selector = selectors.DefaultSelector()
    try:
        with tempfile.TemporaryDirectory(prefix="lifejacket-receiver-") as temp:
            configfile = Path(temp) / "mediamtx.yml"
            configfile.write_text(json.dumps(config))
            media = subprocess.Popen(
                [args.mediamtx, str(configfile)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            last = 0
            print(
                "Private receiver starting; sampled preview at 2 fps. "
                "No flight connection claimed.",
                flush=True,
            )
            try:
                while media.poll() is None and thread.is_alive():
                    if time.monotonic() - last > 1:
                        last = time.monotonic()
                        with SessionLocal() as db:
                            rows = db.scalars(
                                select(CaseDroneStreamRow).where(
                                    CaseDroneStreamRow.ended_at.is_(None)
                                )
                            ).all()
                            active = {row.stream_id for row in rows if streams.active(db, row)}
                            for row in rows:
                                if row.stream_id not in active and row.frames_json:
                                    row.frames_json = []
                            db.commit()
                        try:
                            paths = control("paths/list").get("items", [])
                        except Exception:
                            paths = []
                        ready = {
                            p["name"].split("/")[-1]
                            for p in paths
                            if p.get("ready") and p["name"].startswith("live/")
                        }
                        for p in paths:
                            sid = p["name"].split("/")[-1]
                            source = p.get("source") or {}
                            if sid not in active and source.get("type") == "rtmpConn":
                                with contextlib.suppress(Exception):
                                    control("rtmpconns/kick/" + source["id"], "POST")
                        for sid in list(children):
                            child = children[sid]
                            if (
                                sid not in active
                                or sid not in ready
                                or child["process"].poll() is not None
                            ):
                                stop(selector, children.pop(sid))
                        for sid in sorted(active & ready):
                            if sid in children or len(children) >= 4:
                                continue
                            secret = settings.drone_stream_receiver_secret
                            url = "rtsp://receiver:" + secret + "@127.0.0.1:18554/live/" + sid
                            command = [
                                args.ffmpeg,
                                "-nostdin",
                                "-hide_banner",
                                "-loglevel",
                                "error",
                                "-threads",
                                "1",
                                "-rtsp_transport",
                                "tcp",
                                "-i",
                                url,
                                "-an",
                                "-vf",
                                "fps=2,scale=640:-2",
                                "-threads",
                                "1",
                                "-q:v",
                                "5",
                                "-f",
                                "image2pipe",
                                "-vcodec",
                                "mjpeg",
                                "pipe:1",
                            ]
                            process = subprocess.Popen(
                                command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                            )
                            os.set_blocking(process.stdout.fileno(), False)
                            children[sid] = {"process": process, "buffer": b""}
                            selector.register(process.stdout, selectors.EVENT_READ, sid)
                    for key, _ in selector.select(timeout=0.1):
                        sid = key.data
                        child = children.get(sid)
                        if child is None:
                            continue
                        data = os.read(key.fileobj.fileno(), 65536)
                        child["buffer"] += data
                        while b"\xff\xd9" in child["buffer"]:
                            end = child["buffer"].index(b"\xff\xd9") + 2
                            jpeg, child["buffer"] = (
                                child["buffer"][:end],
                                child["buffer"][end:],
                            )
                            try:
                                with SessionLocal() as db:
                                    streams.receive(db, sid, jpeg)
                            except (ValueError, OSError, HTTPException):
                                pass
                        if len(child["buffer"]) > 512 * 1024:
                            stop(selector, children.pop(sid))
                raise RuntimeError("Receiver process stopped; check binary/configuration")
            finally:
                for child in children.values():
                    stop(selector, child)
                media.terminate()
                try:
                    media.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    media.kill()
                    media.wait()
    finally:
        server.should_exit = True
        selector.close()
        lock.close()


def stop(selector, child):
    process = child["process"]
    with contextlib.suppress(KeyError):
        selector.unregister(process.stdout)
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    process.stdout.close()


if __name__ == "__main__":
    import signal

    def shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mediamtx", required=True, help="MediaMTX v1.21.3 executable")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument(
        "--bind", default="127.0.0.1", help="Private/VPN interface only; defaults to loopback"
    )
    args = parser.parse_args()
    # Avoid arbitrary shell/config injection and accidental public exposure.
    import ipaddress

    address = ipaddress.ip_address(args.bind)
    if not address.is_private or address.is_unspecified:
        parser.error("Bind to a private/VPN address")
    with contextlib.suppress(KeyboardInterrupt):
        run(args)
