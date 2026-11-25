"""Build a short, simulated first pass inside a saved observation search area."""

from fastapi import HTTPException
from pydantic import Field, ValidationError

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


class PatrolRequest(DroneModel):
    plan_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{24}$")


class PatrolPreview(DroneModel):
    plan: DronePlan | None = None
    simulation: DroneSimulationResult | None = None
    unavailable_reason: str | None = None


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
    if body.plan_id is None:
        return PatrolPreview(plan=plan)
    if body.plan_id != plan.plan_id:
        raise HTTPException(409, "Patrol plan changed; preview it again")
    if plan.status == "blocked":
        raise HTTPException(409, "Blocked patrol plans cannot run")
    simulation = MockSimulator().run(plan, "nominal", reviewed_by)
    return PatrolPreview(plan=plan, simulation=simulation)
