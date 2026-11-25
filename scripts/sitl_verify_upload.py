"""Upload and read back the invented demo mission from local ArduCopter SITL.

This integration check does not arm or start a flight. Run with PYTHONPATH=backend.
"""

import json

from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.sitl import mission_items, readback_mission, upload_mission
from pymavlink import mavutil


def main():
    plan = plan_mission(demo_mission())
    items = mission_items(plan, plan.plan_id)
    link = mavutil.mavlink_connection("tcp:127.0.0.1:5760", source_system=255)
    try:
        heartbeat = link.wait_heartbeat(timeout=15)
        if heartbeat is None:
            raise TimeoutError("No SITL heartbeat")
        # pymavlink leaves target_component at broadcast (0) after heartbeat.
        link.target_system = heartbeat.get_srcSystem()
        link.target_component = heartbeat.get_srcComponent()
        upload_mission(link, items)
        count = readback_mission(link, items)
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
