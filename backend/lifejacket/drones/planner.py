"""Bounded lawnmower survey plans for synthetic California test areas."""

import hashlib
import json
import math

from lifejacket.config import load_drone_simulation_config
from lifejacket.geo import haversine_km
from lifejacket.models.drone import (
    DroneMissionRequest,
    DronePlan,
    DronePoint,
    DroneWaypoint,
    SimulationLimits,
    SurveyBox,
)


def distance_m(a: DronePoint, b: DronePoint) -> float:
    return 1000 * haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)


def segment_duration(a: DroneWaypoint, b: DroneWaypoint, limits: SimulationLimits) -> float:
    return (
        distance_m(a, b) / limits.cruise_speed_mps
        + abs(b.altitude_m - a.altitude_m) / limits.vertical_speed_mps
    )


def intersects(a: DronePoint, b: DronePoint, box: SurveyBox) -> bool:
    """Closed rectangle/segment intersection, including transit and boundary contact."""
    low, high = 0.0, 1.0
    for start, delta, minimum, maximum in (
        (a.longitude, b.longitude - a.longitude, box.west, box.east),
        (a.latitude, b.latitude - a.latitude, box.south, box.north),
    ):
        if delta == 0:
            if not minimum <= start <= maximum:
                return False
        else:
            first, last = sorted(((minimum - start) / delta, (maximum - start) / delta))
            low, high = max(low, first), min(high, last)
            if low > high:
                return False
    return True


def _identify(plan: DronePlan) -> DronePlan:
    # Bind review to the actual generated route and limits, including future
    # planner changes, rather than only hashing the submitted intent.
    payload = json.dumps(
        plan.model_dump(exclude={"plan_id"}), sort_keys=True, separators=(",", ":")
    )
    return plan.model_copy(
        update={"plan_id": hashlib.sha256(payload.encode()).hexdigest()[:24]}
    )


def plan_mission(mission: DroneMissionRequest) -> DronePlan:
    limits = SimulationLimits.model_validate(load_drone_simulation_config())
    reasons: list[str] = []
    if not limits.min_altitude_m <= mission.altitude_m <= limits.max_altitude_m:
        reasons.append("Requested altitude is outside the simulation profile")
    if mission.simulated_wind_mps > limits.max_wind_mps:
        reasons.append("Simulated wind exceeds the simulation profile")
    area = mission.survey_area
    corners = [
        DronePoint(latitude=lat, longitude=lon)
        for lat in (area.south, area.north)
        for lon in (area.west, area.east)
    ]
    if any(distance_m(mission.home, corner) > limits.max_home_radius_m for corner in corners):
        reasons.append("Survey area exceeds the maximum distance from home")
        return _identify(
            DronePlan(
                plan_id="",
                status="blocked",
                mission=mission,
                limits=limits,
                waypoints=[],
                blocked_reasons=reasons,
                distance_m=None,
                duration_s=None,
                estimated_battery_remaining_percent=None,
            )
        )

    def point(lat, lon, altitude, phase):
        return DroneWaypoint(latitude=lat, longitude=lon, altitude_m=altitude, phase=phase)

    home = mission.home
    altitude = mission.altitude_m
    waypoints = [
        point(home.latitude, home.longitude, 0, "ground"),
        point(home.latitude, home.longitude, altitude, "takeoff"),
    ]
    height = distance_m(corners[0], corners[2])
    rows = max(1, math.ceil(height / limits.survey_spacing_m))
    # Bound allocation even if someone changes the server's profile drastically.
    if rows > 100:
        raise ValueError("Simulation profile produces more than 100 survey rows")
    for index in range(rows + 1):
        latitude = area.south + (area.north - area.south) * index / rows
        ends = (area.west, area.east) if index % 2 == 0 else (area.east, area.west)
        waypoints.extend(point(latitude, longitude, altitude, "survey") for longitude in ends)
    waypoints.extend(
        [
            point(home.latitude, home.longitude, altitude, "return"),
            point(home.latitude, home.longitude, 0, "land"),
        ]
    )
    segments = list(zip(waypoints, waypoints[1:], strict=False))
    distance = sum(distance_m(a, b) for a, b in segments)
    duration = sum(segment_duration(a, b, limits) for a, b in segments)
    remaining = 100 * (1 - duration / limits.endurance_s)
    if distance > limits.max_route_m:
        reasons.append("Route exceeds the simulated distance budget")
    if remaining < limits.reserve_percent:
        reasons.append("Route would consume the simulated battery reserve")
    if any(intersects(a, b, zone) for a, b in segments for zone in mission.exclusion_zones):
        reasons.append("Route or transit intersects a supplied exclusion zone")
    return _identify(
        DronePlan(
            plan_id="",
            status="blocked" if reasons else "ready_for_review",
            mission=mission,
            limits=limits,
            waypoints=waypoints,
            blocked_reasons=reasons,
            distance_m=round(distance, 1),
            duration_s=round(duration, 1),
            estimated_battery_remaining_percent=round(max(0, remaining), 1),
        )
    )


def demo_mission() -> DroneMissionRequest:
    """Invented base and area. No NOAA record or real animal location is used."""
    return DroneMissionRequest(
        home=DronePoint(latitude=36.8, longitude=-121.801),
        survey_area=SurveyBox(south=36.8008, north=36.8028, west=-121.8, east=-121.798),
    )
