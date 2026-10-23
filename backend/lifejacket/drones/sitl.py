"""Mission upload protocol for a separately launched local ArduPilot SITL.

No arming, mode changes or flight execution. Transport creation belongs to the
local companion process, never the public API.
"""

import time
from dataclasses import dataclass

from lifejacket.drones.planner import plan_mission
from lifejacket.models.drone import DronePlan


@dataclass(frozen=True)
class MissionItem:
    sequence: int
    command: int
    latitude_int: int
    longitude_int: int
    altitude_m: float


def mission_items(plan: DronePlan, reviewed_plan_id: str) -> list[MissionItem]:
    """Rebuild server intent before translating; reject stale or altered plans."""
    current = plan_mission(plan.mission)
    if current != plan or current.plan_id != reviewed_plan_id:
        raise ValueError("Plan changed; regenerate and review before upload")
    if current.status != "ready_for_review":
        raise ValueError("Blocked plans cannot be uploaded")
    # ArduPilot stores home at index zero; it is not a flown navigation leg.
    commands = {"ground": 16, "takeoff": 22, "survey": 16, "return": 16, "land": 21}
    return [
        MissionItem(
            i,
            commands[p.phase],
            round(p.latitude * 1e7),
            round(p.longitude * 1e7),
            p.altitude_m,
        )
        for i, p in enumerate(current.waypoints)
    ]


def upload_mission(connection, items: list[MissionItem], timeout_s: float = 30) -> None:
    """Handle requested items (including retries), then require an accepted ACK.

    Connection is an already selected pymavlink transport. No clearing of the
    previous mission is necessary: MISSION_COUNT begins replacement upload.
    Failure means upload is unconfirmed, not that the old mission is preserved.
    """
    if not items or timeout_s <= 0:
        raise ValueError("A nonempty mission and positive timeout are required")
    if [item.sequence for item in items] != list(range(len(items))):
        raise ValueError("Mission sequence must be contiguous from zero")
    system, component = connection.target_system, connection.target_component
    connection.mav.mission_count_send(system, component, len(items))
    deadline = time.monotonic() + timeout_s
    sent = set()
    while (remaining := deadline - time.monotonic()) > 0:
        message = connection.recv_match(
            type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"],
            blocking=True,
            timeout=remaining,
        )
        if message is None:
            break
        if message.get_srcSystem() != system or message.get_srcComponent() != component:
            continue
        if getattr(message, "mission_type", 0) != 0:
            continue
        kind = message.get_type()
        if kind == "MISSION_ACK":
            if message.type != 0:
                raise RuntimeError(
                    f"Autopilot rejected mission: MAV_MISSION_RESULT={message.type}"
                )
            if len(sent) != len(items):
                raise RuntimeError("Premature mission acknowledgment")
            return
        if not 0 <= message.seq < len(items):
            raise RuntimeError("Autopilot requested an invalid mission sequence")
        item = items[message.seq]
        # MAV_FRAME_GLOBAL_RELATIVE_ALT_INT for integer transfer, otherwise
        # MAV_FRAME_GLOBAL_RELATIVE_ALT. Altitude is relative to SITL home.
        args = (
            system,
            component,
            item.sequence,
            6 if kind == "MISSION_REQUEST_INT" else 3,
            item.command,
            0,
            1,
            0,
            0,
            0,
            0,
        )
        if kind == "MISSION_REQUEST_INT":
            connection.mav.mission_item_int_send(
                *args, item.latitude_int, item.longitude_int, item.altitude_m
            )
        else:
            connection.mav.mission_item_send(
                *args, item.latitude_int / 1e7, item.longitude_int / 1e7, item.altitude_m
            )
        sent.add(item.sequence)
    raise TimeoutError("Mission upload timed out without an accepted acknowledgment")
