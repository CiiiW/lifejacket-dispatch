"""Simulation contracts; optional historical context is real aggregate evidence only."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DroneModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DronePoint(DroneModel):
    # Broad California demo bounds, not a coastline or flight authorization.
    latitude: float = Field(ge=32, le=42.5, strict=True)
    longitude: float = Field(ge=-125, le=-114, strict=True)


class SurveyBox(DroneModel):
    south: float = Field(ge=32, le=42.5, strict=True)
    north: float = Field(ge=32, le=42.5, strict=True)
    west: float = Field(ge=-125, le=-114, strict=True)
    east: float = Field(ge=-125, le=-114, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.south >= self.north or self.west >= self.east:
            raise ValueError("Survey bounds must have positive width and height")
        return self


class HistoricalSurveyContext(DroneModel):
    dataset_id: Literal["noaa_ca_2006_2025"] = "noaa_ca_2006_2025"
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    latitude_index: int = Field(ge=320, le=424, strict=True)
    longitude_index: int = Field(ge=-1250, le=-1141, strict=True)


class DroneMissionRequest(DroneModel):
    mode: Literal["simulation"] = "simulation"
    home: DronePoint
    survey_area: SurveyBox
    altitude_m: float = Field(default=60, gt=0, le=1000, strict=True)
    simulated_wind_mps: float = Field(default=3, ge=0, le=60, strict=True)
    exclusion_zones: list[SurveyBox] = Field(default_factory=list, max_length=20)
    historical_context: HistoricalSurveyContext | None = None


class SimulationLimits(DroneModel):
    """Server-owned test assumptions, not aircraft specifications or legal limits."""

    min_altitude_m: float = Field(gt=0)
    max_altitude_m: float = Field(gt=0)
    max_home_radius_m: float = Field(gt=0)
    max_route_m: float = Field(gt=0)
    max_wind_mps: float = Field(ge=0)
    cruise_speed_mps: float = Field(gt=0)
    vertical_speed_mps: float = Field(gt=0)
    endurance_s: float = Field(gt=0)
    reserve_percent: float = Field(ge=0, lt=100)
    survey_spacing_m: float = Field(ge=10)
    sample_period_s: float = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.min_altitude_m > self.max_altitude_m:
            raise ValueError("Minimum altitude exceeds maximum altitude")
        return self


class DroneWaypoint(DronePoint):
    altitude_m: float = Field(ge=0)
    phase: Literal["ground", "takeoff", "survey", "return", "land"]


class DronePlan(DroneModel):
    plan_id: str
    status: Literal["ready_for_review", "blocked"]
    mission: DroneMissionRequest
    limits: SimulationLimits
    waypoints: list[DroneWaypoint]
    blocked_reasons: list[str]
    distance_m: float | None
    duration_s: float | None
    estimated_battery_remaining_percent: float | None
    synthetic: Literal[True] = True


Scenario = Literal["nominal", "low_battery", "link_loss"]


class DroneSimulationRequest(DroneModel):
    mission: DroneMissionRequest
    plan_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    # A demo review acknowledgment, not a verified identity or authorization.
    reviewed_by: str = Field(min_length=1, max_length=80, pattern=r"\S")
    backend: Literal["mock"] = "mock"
    scenario: Scenario = "nominal"


class DroneTelemetry(DroneWaypoint):
    elapsed_s: float
    battery_percent: float


class DroneSimulationEvent(DroneModel):
    elapsed_s: float
    kind: str
    message: str


class DroneSimulationResult(DroneModel):
    run_id: str
    plan_id: str
    backend: Literal["mock"] = "mock"
    synthetic: Literal[True] = True
    scenario: Scenario
    status: Literal["completed", "aborted"]
    reviewed_by: str
    samples: list[DroneTelemetry]
    events: list[DroneSimulationEvent]
    limitations: list[str]
