"""A kinematic mock behind a simulator interface; it never opens a vehicle connection."""

import math
from typing import Protocol
from uuid import uuid4

from lifejacket.drones.planner import segment_duration
from lifejacket.models.drone import (
    DronePlan,
    DroneSimulationEvent,
    DroneSimulationResult,
    DroneTelemetry,
    Scenario,
)


class Simulator(Protocol):
    """Future SITL adapters implement this contract in a separate worker process."""

    def run(
        self, plan: DronePlan, scenario: Scenario, reviewed_by: str
    ) -> DroneSimulationResult: ...


class MockSimulator:
    def run(
        self, plan: DronePlan, scenario: Scenario, reviewed_by: str
    ) -> DroneSimulationResult:
        if plan.status != "ready_for_review":
            raise ValueError("Blocked plans cannot run")
        if not reviewed_by.strip():
            raise ValueError("Record a simulation review before running")
        samples = [
            DroneTelemetry(**plan.waypoints[0].model_dump(), elapsed_s=0, battery_percent=100)
        ]
        elapsed = 0.0
        events: list[DroneSimulationEvent] = []
        status = "completed"
        fault_at = (plan.duration_s or 0) / 2
        for a, b in zip(plan.waypoints, plan.waypoints[1:], strict=False):
            duration = segment_duration(a, b, plan.limits)
            steps = max(1, math.ceil(duration / plan.limits.sample_period_s))
            for index in range(1, steps + 1):
                fraction = index / steps
                timestamp = elapsed + duration * fraction
                battery = max(0, 100 * (1 - timestamp / plan.limits.endurance_s))
                fault = scenario != "nominal" and timestamp >= fault_at
                if fault and scenario == "low_battery":
                    battery = max(0, plan.limits.reserve_percent - 5)
                samples.append(
                    DroneTelemetry(
                        latitude=round(a.latitude + (b.latitude - a.latitude) * fraction, 7),
                        longitude=round(
                            a.longitude + (b.longitude - a.longitude) * fraction, 7
                        ),
                        altitude_m=round(
                            a.altitude_m + (b.altitude_m - a.altitude_m) * fraction, 2
                        ),
                        phase=b.phase,
                        elapsed_s=round(timestamp, 2),
                        battery_percent=round(battery, 2),
                    )
                )
                if fault:
                    events.append(
                        DroneSimulationEvent(
                            elapsed_s=round(timestamp, 2),
                            kind=scenario,
                            message=(
                                "Injected mock fault stopped the replay; "
                                "autopilot recovery is not modeled."
                            ),
                        )
                    )
                    status = "aborted"
                    break
            if status == "aborted":
                break
            elapsed += duration
        return DroneSimulationResult(
            run_id=uuid4().hex,
            plan_id=plan.plan_id,
            scenario=scenario,
            status=status,
            reviewed_by=reviewed_by.strip(),
            samples=samples,
            events=events,
            limitations=[
                "Synthetic constant-speed motion and linear battery consumption; "
                "no flight dynamics.",
                "Wind is a planning check only; terrain, obstacles, camera coverage "
                "and airspace are not modeled.",
                "No vehicle connection, arming command, wildlife interaction, "
                "or flight authorization.",
            ],
        )
