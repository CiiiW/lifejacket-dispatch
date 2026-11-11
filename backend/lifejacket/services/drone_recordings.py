"""Private, bounded recordings of the RECEIVED stream, never aircraft originals."""

import hashlib
import json
import math
import shutil
import signal
import subprocess
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from lifejacket.config import settings
from lifejacket.models.tables import CaseDroneRecordingRow
from lifejacket.services import drone_requests as requests

MAX_SEGMENT_BYTES = 64 * 1024 * 1024
MAX_SESSION_BYTES = 512 * 1024 * 1024


def root():
    return settings.drone_evidence_dir / "stream-recordings"


def rows(db, stream_id):
    return db.scalars(
        select(CaseDroneRecordingRow)
        .where(CaseDroneRecordingRow.stream_id == stream_id)
        .order_by(CaseDroneRecordingRow.started_at)
    ).all()


def listing(db, stream_id):
    result = []
    for row in rows(db, stream_id):
        status = row.status
        if status == "recording" and (requests.now() - row.updated_at).total_seconds() > 10:
            status = "interrupted"
        result.append(
            {
                "recording_id": row.recording_id,
                "status": status,
                "started_at": row.started_at.isoformat() + "Z",
                "updated_at": row.updated_at.isoformat() + "Z",
                "segments": row.segments_json,
                "error_code": row.error_code,
            }
        )
    return {
        "enabled": settings.drone_recordings_enabled,
        "recordings": result,
        "time_note": "Received stream; server start time, not camera capture time.",
    }


def segment(db, stream_id, recording_id, segment_id):
    row = db.get(CaseDroneRecordingRow, recording_id)
    if row is None or row.stream_id != stream_id:
        raise HTTPException(404, "Recording unavailable")
    entry = next((s for s in row.segments_json if s["segment_id"] == segment_id), None)
    if entry is None:
        raise HTTPException(404, "Recording unavailable")
    path = root() / row.recording_id / (entry["segment_id"] + ".mp4")
    if not path.is_file() or path.stat().st_size != entry["bytes"]:
        raise HTTPException(404, "Recording file unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise HTTPException(409, "Recording integrity check failed")
    return path


class Recorder:
    """One FFmpeg reader per connection. Only closed MP4 segments are published."""

    def __init__(self, factory, stream_id, url, ffmpeg, ffprobe="ffprobe"):
        self.factory, self.stream_id, self.ffprobe = factory, stream_id, ffprobe
        self.recording_id = uuid.uuid4().hex
        self.directory = root() / self.recording_id
        self.directory.mkdir(parents=True, mode=0o700)
        self.process = None
        recovery = []
        with factory() as db:
            # A crashed previous recorder cannot finalize its partial last segment.
            for row in rows(db, stream_id):
                if row.status == "recording":
                    row.status = "interrupted"
                    row.error_code = "receiver_restarted"
                    recovery.append(row.recording_id)
            db.add(
                CaseDroneRecordingRow(
                    recording_id=self.recording_id,
                    stream_id=stream_id,
                    status="recording",
                    started_at=requests.now(),
                    updated_at=requests.now(),
                    segments_json=[],
                )
            )
            db.commit()
        for recording_id in recovery:
            previous = object.__new__(Recorder)
            previous.factory, previous.stream_id = factory, stream_id
            previous.ffprobe, previous.recording_id = ffprobe, recording_id
            previous.directory, previous.process = root() / recording_id, None
            previous.finish("interrupted", "receiver_restarted")
        with factory() as db:
            directories = [root() / r.recording_id for r in rows(db, stream_id)]
        existing_bytes = sum(p.stat().st_size for d in directories for p in d.glob("*.mp4"))
        if (
            existing_bytes >= MAX_SESSION_BYTES
            or shutil.disk_usage(root()).free < 128 * 1024 * 1024
        ):
            self.finish("limited", "storage_limit")
            raise OSError("Recording storage limit reached")
        try:
            self.process = subprocess.Popen(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    url,
                    "-map",
                    "0:v:0",
                    "-an",
                    "-c:v",
                    "copy",
                    "-t",
                    "1800",
                    "-f",
                    "segment",
                    "-segment_time",
                    "10",
                    "-reset_timestamps",
                    "1",
                    "-segment_format",
                    "mp4",
                    "-segment_format_options",
                    "movflags=+faststart",
                    "-segment_list",
                    str(self.directory / "segments.csv"),
                    "-segment_list_type",
                    "csv",
                    str(self.directory / "%06d.mp4"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.finish("failed", "recorder_start_failed")
            raise

    def poll(self):
        import csv

        manifest = self.directory / "segments.csv"
        with self.factory() as db:
            row = db.get(CaseDroneRecordingRow, self.recording_id)
            known = {s["segment_id"] for s in row.segments_json}
            entries = list(row.segments_json)
            if manifest.exists():
                with manifest.open(newline="") as handle:
                    lines = list(csv.reader(handle))
                for line in lines:
                    if len(line) != 3:
                        continue
                    name = Path(line[0]).name
                    if not (len(name) == 10 and name[:6].isdigit() and name.endswith(".mp4")):
                        continue
                    sid = name[:-4]
                    if sid in known:
                        continue
                    path = self.directory / name
                    size = path.stat().st_size if path.is_file() else 0
                    if not 0 < size <= MAX_SEGMENT_BYTES:
                        continue
                    try:
                        start, end = float(line[1]), float(line[2])
                        probe = subprocess.run(
                            [
                                self.ffprobe,
                                "-v",
                                "error",
                                "-show_format",
                                "-of",
                                "json",
                                str(path),
                            ],
                            capture_output=True,
                            timeout=10,
                            check=True,
                        )
                        duration = float(json.loads(probe.stdout)["format"]["duration"])
                        if not all(math.isfinite(v) for v in (start, end, duration)):
                            continue
                        if start < 0 or end <= start or not 0 < duration <= 1800:
                            continue
                    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
                        continue
                    entries.append(
                        {
                            "segment_id": sid,
                            "offset_seconds": start,
                            "duration_seconds": duration,
                            "bytes": size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    )
                    known.add(sid)
            row.segments_json = entries
            row.updated_at = requests.now()
            db.commit()
        # Include open files and prior reconnects in the per-session storage ceiling.
        with self.factory() as db:
            directories = [root() / r.recording_id for r in rows(db, self.stream_id)]
        total = sum(p.stat().st_size for d in directories for p in d.glob("*.mp4"))
        return total >= MAX_SESSION_BYTES or shutil.disk_usage(root()).free < 128 * 1024 * 1024

    def finish(self, status="complete", error=None):
        if self.process and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                status, error = "interrupted", "recorder_stop_timeout"
        self.poll()
        with self.factory() as db:
            row = db.get(CaseDroneRecordingRow, self.recording_id)
            if not row.segments_json and error is None:
                status, error = "failed", "no_playable_segments"
            row.status, row.error_code, row.updated_at = status, error, requests.now()
            db.commit()
        # Unindexed files are incomplete/unplayable, not evidence.
        with self.factory() as db:
            row = db.get(CaseDroneRecordingRow, self.recording_id)
            kept = {s["segment_id"] + ".mp4" for s in row.segments_json}
        for path in self.directory.glob("*.mp4"):
            if path.name not in kept:
                path.unlink(missing_ok=True)
