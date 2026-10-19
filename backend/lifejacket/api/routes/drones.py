"""Stateless simulations; historical context optionally reads the local aggregate DB."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lifejacket.drones.historical import validate_historical_context
from lifejacket.drones.planner import demo_mission, plan_mission
from lifejacket.drones.simulator import MockSimulator
from lifejacket.models.db import get_session
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
def plan(body: DroneMissionRequest, session: Session = Depends(get_session)) -> DronePlan:
    _validate_context(body, session)
    return plan_mission(body)


@router.post("/simulate", response_model=DroneSimulationResult)
def simulate(
    body: DroneSimulationRequest, session: Session = Depends(get_session)
) -> DroneSimulationResult:
    _validate_context(body.mission, session)
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


def _validate_context(mission: DroneMissionRequest, session: Session) -> None:
    try:
        validate_historical_context(mission, session)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
