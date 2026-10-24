"""Upload a reviewed plan to local SITL; does not arm or start a flight."""

import argparse
from pathlib import Path

from lifejacket.drones.sitl import mission_items, upload_mission
from lifejacket.models.drone import DronePlan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="JSON response from /drones/plan")
    parser.add_argument("--reviewed-plan-id", required=True)
    args = parser.parse_args()
    plan = DronePlan.model_validate_json(args.plan.read_text())
    items = mission_items(plan, args.reviewed_plan_id)
    from pymavlink import mavutil

    # Fixed loopback endpoint: no serial devices or arbitrary remote hosts.
    link = mavutil.mavlink_connection("tcp:127.0.0.1:5760", source_system=255)
    try:
        heartbeat = link.wait_heartbeat(timeout=15)
        if heartbeat is None:
            raise TimeoutError("No SITL heartbeat on localhost:5760")
        # pymavlink leaves target_component at broadcast (0) after heartbeat.
        link.target_system = heartbeat.get_srcSystem()
        link.target_component = heartbeat.get_srcComponent()
        upload_mission(link, items)
        print(f"Upload accepted: {plan.plan_id}, {len(items)} items. Flight not started.")
    finally:
        link.close()


if __name__ == "__main__":
    main()
