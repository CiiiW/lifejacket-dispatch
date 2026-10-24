"""Atomic local run snapshots shared by the companion worker and read-only API."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

RUN_ID = re.compile(r"^[0-9a-f]{32}$")
TERMINAL = {"completed", "aborted", "failed", "interrupted", "unconfirmed"}


def run_path(root: Path, run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run ID")
    return root / f"{run_id}.json"


def save_run(root: Path, run: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    path = run_path(root, run["run_id"])
    run["updated_at"] = datetime.now(UTC).isoformat()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(run, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def load_run(root: Path, run_id: str) -> dict:
    return json.loads(run_path(root, run_id).read_text(encoding="utf-8"))


def list_runs(root: Path, limit: int = 30) -> list[dict]:
    if not root.exists():
        return []
    result = []
    for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not RUN_ID.fullmatch(path.stem):
            continue
        run = load_run(root, path.stem)
        result.append(
            {
                key: value
                for key, value in run.items()
                if key not in {"samples", "events", "plan"}
            }
        )
        if len(result) >= limit:
            break
    return result


def reconcile_interrupted(root: Path) -> int:
    """Call only while holding the exclusive worker lock; never resume a mission."""
    count = 0
    for run in list_runs(root, limit=10000):
        if run["status"] not in TERMINAL:
            full = load_run(root, run["run_id"])
            full.update(
                status="interrupted", outcome="Worker stopped; vehicle state unconfirmed"
            )
            save_run(root, full)
            count += 1
    return count
