"""Stateless simulation endpoints. No database, cloud identity or drone is required."""

from fastapi import APIRouter, HTTPException

from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.simulator import MockSimulator
from lifejacket.models.drone import (
    DroneMissionRequest,
    DronePlan,
    DroneSimulationRequest,
    DroneSimulationResult,
)

router = APIRouter(prefix="/drones", tags=["drone simulation"])


@router.get("/demo", response_model=DroneMissionRequest)
def demo() -> DroneMissionRequest:
    return demo_mission()


@router.post("/plan", response_model=DronePlan)
def plan(body: DroneMissionRequest) -> DronePlan:
    return plan_mission(body)


@router.post("/simulate", response_model=DroneSimulationResult)
def simulate(body: DroneSimulationRequest) -> DroneSimulationResult:
    # Rebuild from intent and server-owned limits; never execute client waypoints.
    current = plan_mission(body.mission)
    if current.plan_id != body.plan_id:
        raise HTTPException(
            status_code=409, detail="Mission or profile changed; plan and review again"
        )
    if current.status == "blocked":
        raise HTTPException(status_code=409, detail="; ".join(current.blocked_reasons))
    # Only this mock is registered. The API does not accept a host, port or device path.
    return MockSimulator().run(current, body.scenario, body.reviewed_by)
