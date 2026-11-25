"""Pair one iPhone H.264 publisher to an existing private LifeJacket stream."""

import argparse
import asyncio
import ipaddress
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import uvicorn
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

MAX_CHUNK = 512 * 1024
SESSION_SECONDS = 30 * 60
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def private_ip(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError("Use a private IPv4 address")
    return str(address)


def publish_url_from(path):
    if path.stat().st_mode & 0o077:
        raise ValueError("Set the publishing-address file permissions to 600")
    url = path.read_text(encoding="utf-8").strip()
    parts = urlsplit(url)
    private_ip(parts.hostname or "")
    query = parse_qs(parts.query)
    tokens = query.get("pass", [])
    if (
        parts.scheme != "rtmp"
        or parts.port != 19350
        or parts.username
        or parts.password
        or parts.fragment
        or not re.fullmatch(r"/live/[a-f0-9]{32}", parts.path)
        or set(query) != {"user", "pass"}
        or query["user"] != ["publisher"]
        or len(tokens) != 1
        or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", tokens[0])
    ):
        raise ValueError("Expected an existing private LifeJacket publishing address")
    return url


def create_app(publish_url, code, ffmpeg, fps):
    app = FastAPI(openapi_url=None)
    expiration = time.monotonic() + SESSION_SECONDS
    publisher = asyncio.Lock()
    credential = f"Bearer {code}".encode()

    @app.websocket("/camera")
    async def camera(socket: WebSocket):
        supplied = socket.headers.get("authorization", "").encode()
        if (
            socket.headers.get("origin")
            or not secrets.compare_digest(supplied, credential)
            or publisher.locked()
            or time.monotonic() >= expiration
        ):
            await socket.close(code=1008)
            return
        async with publisher:
            await socket.accept()
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-probesize",
                    "1000000",
                    "-analyzeduration",
                    "1000000",
                    "-framerate",
                    str(fps),
                    "-f",
                    "h264",
                    "-threads",
                    "2",
                    "-max_pixels",
                    "8294400",
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-threads",
                    "2",
                    "-preset",
                    "ultrafast",
                    "-tune",
                    "zerolatency",
                    "-pix_fmt",
                    "yuv420p",
                    "-g",
                    str(fps),
                    "-flvflags",
                    "no_duration_filesize",
                    "-f",
                    "flv",
                    publish_url,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                while (remaining := expiration - time.monotonic()) > 0:
                    message = await asyncio.wait_for(socket.receive(), min(6, remaining))
                    if message["type"] == "websocket.disconnect":
                        return
                    data = message.get("bytes")
                    if not data or len(data) > MAX_CHUNK:
                        await socket.close(code=1003, reason="Expected bounded H.264 data")
                        return
                    process.stdin.write(data)
                    await asyncio.wait_for(process.stdin.drain(), 6)
                await socket.close(code=1000, reason="Pairing expired")
            except WebSocketDisconnect:
                pass
            except (OSError, TimeoutError):
                await socket.close(code=1011, reason="Camera idle or RTMP unavailable")
            finally:
                if process:
                    process.stdin.close()
                    try:
                        await asyncio.wait_for(process.wait(), 2)
                    except TimeoutError:
                        if process.returncode is None:
                            process.kill()
                        await process.wait()

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--grant-url-file", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--fps", type=int, choices=(24, 25, 30), default=30)
    args = parser.parse_args()
    try:
        host = private_ip(args.bind)
        url = publish_url_from(args.grant_url_file)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    code = secrets.token_urlsafe(24)
    print(f"Private iPhone relay: ws://{host}:{args.port}/camera", flush=True)
    print(f"Pairing code (expires in 30 minutes): {code}", flush=True)
    uvicorn.run(
        create_app(url, code, args.ffmpeg, args.fps),
        host=host,
        port=args.port,
        access_log=False,
        log_level="warning",
        ws="websockets",
        ws_max_size=MAX_CHUNK,
        ws_max_queue=4,
        ws_per_message_deflate=False,
    )


if __name__ == "__main__":
    main()
