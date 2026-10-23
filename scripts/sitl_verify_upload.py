"""Upload and read back the invented demo mission from local ArduCopter SITL.

This integration check does not arm or start a flight. Run with PYTHONPATH=backend.
"""

import json
import time

from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.sitl import mission_items, upload_mission
from pymavlink import mavutil


def receive(link, kind, timeout=10):
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        msg = link.recv_match(type=kind, blocking=True, timeout=remaining)
        if msg is None:
            break
        if (msg.get_srcSystem(), msg.get_srcComponent()) == (
            link.target_system,
            link.target_component,
        ):
            return msg
    raise TimeoutError(f"No {kind} from SITL")


def main():
    plan = plan_mission(demo_mission())
    items = mission_items(plan, plan.plan_id)
    link = mavutil.mavlink_connection("tcp:127.0.0.1:5760", source_system=255)
    try:
        if link.wait_heartbeat(timeout=15) is None:
            raise TimeoutError("No SITL heartbeat")
        system, component = link.target_system, link.target_component
        upload_mission(link, items)
        link.mav.mission_request_list_send(system, component)
        count = receive(link, "MISSION_COUNT").count
        if count != len(items):
            raise RuntimeError(f"Readback count {count}, expected {len(items)}")
        for expected in items:
            link.mav.mission_request_int_send(system, component, expected.sequence)
            actual = receive(link, "MISSION_ITEM_INT")
            if actual.seq != expected.sequence:
                raise RuntimeError("Unexpected sequence during readback")
            # ArduPilot treats index zero as home; validate navigation items.
            if expected.sequence == 0:
                continue
            if (
                actual.command != expected.command
                or abs(actual.x - expected.latitude_int) > 1
                or abs(actual.y - expected.longitude_int) > 1
                or abs(actual.z - expected.altitude_m) > 0.01
            ):
                raise RuntimeError(f"Readback mismatch at item {expected.sequence}")
        link.mav.mission_ack_send(system, component, 0)
        print(
            json.dumps(
                {
                    "backend": "ardupilot_sitl",
                    "plan_id": plan.plan_id,
                    "mission_items": count,
                    "upload_accepted": True,
                    "navigation_readback_matches": True,
                    "flight_started": False,
                },
                indent=2,
            )
        )
    finally:
        link.close()


if __name__ == "__main__":
    main()
