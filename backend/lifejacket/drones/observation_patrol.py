"""Plan, replay or verify a simulator upload for a case observation patrol."""

import logging
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, ValidationError, model_validator

from lifejacket.drones.patrol_sitl import (
    SimulatorBusyError,
    simulator_binary,
    verify_patrol_upload,
)
from lifejacket.drones.planner import plan_mission
from lifejacket.drones.simulator import MockSimulator
from lifejacket.geo import bounding_box
from lifejacket.models.drone import (
    DroneMissionRequest,
    DroneModel,
    DronePlan,
    DroneSimulationResult,
)
from lifejacket.models.drone_requests import ObservationSearchArea

FIRST_PASS_HALF_WIDTH_M = 100
logger = logging.getLogger(__name__)


class PatrolRequest(DroneModel):
    plan_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{24}$")
    send_to_simulator: bool = False

    @model_validator(mode="after")
    def require_review(self) -> "PatrolRequest":
        if self.send_to_simulator and self.plan_id is None:
            raise ValueError("Preview the patrol before sending it to the simulator")
        return self


class PatrolUploadReceipt(DroneModel):
    backend: Literal["ardupilot_sitl"] = "ardupilot_sitl"
    plan_id: str
    mission_items: int
    flight_started: Literal[False] = False


class PatrolPreview(DroneModel):
    plan: DronePlan | None = None
    simulation: DroneSimulationResult | None = None
    unavailable_reason: str | None = None
    simulator_available: bool = False
    upload: PatrolUploadReceipt | None = None


def observation_patrol(
    search_area: ObservationSearchArea, body: PatrolRequest, reviewed_by: str
) -> PatrolPreview:
    center = search_area.center
    if center is None:
        return PatrolPreview(unavailable_reason="Save a search center to preview a patrol.")
    # Leave margin inside the search circle, including the corners of the box.
    half_width_km = min(FIRST_PASS_HALF_WIDTH_M, search_area.radius_m * 0.65) / 1000
    south, north, west, east = bounding_box(center.latitude, center.longitude, half_width_km)
    try:
        mission = DroneMissionRequest(
            home=center.model_dump(),
            survey_area={"south": south, "north": north, "west": west, "east": east},
            altitude_m=20,
        )
    except ValidationError:
        return PatrolPreview(
            unavailable_reason="This search area is outside the California simulation region."
        )
    plan = plan_mission(mission)
    binary = simulator_binary()
    result = PatrolPreview(plan=plan, simulator_available=binary is not None)
    if body.plan_id is None:
        return result
    if body.plan_id != plan.plan_id:
        raise HTTPException(409, "Patrol plan changed; preview it again")
    if plan.status == "blocked":
        raise HTTPException(409, "Blocked patrol plans cannot run")
    if not body.send_to_simulator:
        result.simulation = MockSimulator().run(plan, "nominal", reviewed_by)
        return result
    if binary is None:
        result.unavailable_reason = "ArduPilot simulation is disabled on this server."
        return result
    try:
        count = verify_patrol_upload(binary, plan, body.plan_id)
    except SimulatorBusyError as exc:
        result.unavailable_reason = str(exc)
    except (OSError, RuntimeError, ImportError, ValueError):
        logger.exception("ArduPilot patrol upload could not be verified")
        result.unavailable_reason = "ArduPilot could not verify the upload. Try again."
    else:
        result.upload = PatrolUploadReceipt(plan_id=plan.plan_id, mission_items=count)
    return result
