#!/usr/bin/env python3
"""Run durable follow-up jobs independently of any open browser.

Run one process per kind: AI latency must not block reminder delivery.
"""

import argparse
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from lifejacket.models.db import SessionLocal, init_db
from lifejacket.services import (
    drone_followup as common,
)
from lifejacket.services import (
    drone_frame_analysis as ai,
)
from lifejacket.services import (
    drone_reminders as reminders,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["analysis", "reminders"], required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    (ai.enabled if args.kind == "analysis" else reminders.enabled)()
    init_db()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    def pulse():
        while not stop.is_set():
            try:
                with SessionLocal() as db:
                    common.heartbeat(db, args.kind)
            except Exception:
                pass
            stop.wait(30)

    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    process = ai.process_one if args.kind == "analysis" else reminders.deliver_one
    try:
        while not stop.is_set():
            try:
                worked = process(SessionLocal)
            except Exception:
                # Never log provider payloads, webhook destinations, credentials or images.
                print(
                    "Follow-up worker cycle failed; will retry.", file=sys.stderr, flush=True
                )
                worked = False
            if args.once:
                break
            stop.wait(1 if worked else 15)
    finally:
        stop.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
