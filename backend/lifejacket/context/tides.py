"""Tide state at the incident location, from NOAA CO-OPS.

**Why this module exists.** For a stranded marine mammal, the tide is usually
more decisive than anything else we can measure:

- A **rising** tide may refloat the animal without intervention. The right
  advice is often to watch and wait, and a rushed rescue can cause more harm.
- A **falling** tide strands the animal further from the water with every
  minute. It starts a heat-stress and dehydration clock, and it means a rescue
  team has a hard deadline rather than an open-ended window.

The previous prototype had no tide data at all, so the assessment agent could
not distinguish these two situations. This is the gap that mattered most.

Two sources are combined:

- **NOAA CO-OPS** for tide predictions. Free, keyless, authoritative, and US
  coastal only -- which matches the stranding networks in `rescue_centers.csv`.
- **Open-Meteo Marine** for wave height and sea temperature, which determine
  whether volunteers can safely enter the surf.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from functools import lru_cache
from typing import Any

import httpx

from lifejacket.config import settings
from lifejacket.geo import haversine_km
from lifejacket.models.schemas import TideConditions, TideEvent

logger = logging.getLogger(__name__)

#: Beyond this, a tide station's predictions no longer describe the incident
#: site well enough to act on. Tidal timing shifts meaningfully along a coast.
MAX_STATION_DISTANCE_KM = 75.0


@lru_cache(maxsize=1)
def _load_tide_stations() -> list[dict[str, Any]]:
    """Fetch and cache NOAA's tide-prediction station list.

    Roughly 3,000 stations. Cached for the process lifetime because the list
    changes a few times a year, and we would otherwise download it per
    incident. Returns an empty list on failure so callers degrade gracefully.
    """
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(
                settings.noaa_stations_api_url,
                params={"type": "tidepredictions"},
                headers={"User-Agent": settings.http_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Could not load NOAA tide stations: %s", exc)
        return []

    stations = []
    for station in payload.get("stations", []):
        # Some records carry null coordinates; they are unusable for distance.
        if station.get("lat") is None or station.get("lng") is None:
            continue
        stations.append(
            {
                "id": str(station.get("id")),
                "name": station.get("name") or "",
                "lat": float(station["lat"]),
                "lon": float(station["lng"]),
            }
        )
    return stations


def find_nearest_station(
    latitude: float, longitude: float
) -> tuple[dict[str, Any], float] | None:
    """Nearest tide station and its distance in km, or None if too far inland.

    Returning None for inland locations is deliberate: it is how the pipeline
    decides an incident is not coastal and skips tide reasoning entirely.
    """
    stations = _load_tide_stations()
    if not stations:
        return None

    nearest = min(
        stations,
        key=lambda s: haversine_km(latitude, longitude, s["lat"], s["lon"]),
    )
    distance = haversine_km(latitude, longitude, nearest["lat"], nearest["lon"])

    if distance > MAX_STATION_DISTANCE_KM:
        return None
    return nearest, distance


def fetch_tides(latitude: float, longitude: float) -> TideConditions | None:
    """Tide state at a coastal point, or None if unavailable.

    Queries from the evening before today to the morning after tomorrow: wide
    enough that the next high and low are always found, and that today's
    curve can be drawn midnight to midnight with a turning point either side.
    """
    found = find_nearest_station(latitude, longitude)
    if found is None:
        return None
    station, distance_km = found

    now = datetime.now()
    midnight = datetime.combine(now.date(), time.min)
    params = {
        "product": "predictions",
        "application": "LifeJacketDispatch",
        "station": station["id"],
        "begin_date": (midnight - timedelta(hours=14)).strftime("%Y%m%d %H:%M"),
        "end_date": max(now + timedelta(hours=36), midnight + timedelta(hours=38)).strftime(
            "%Y%m%d %H:%M"
        ),
        "datum": "MLLW",  # NOAA's standard chart datum for US tide predictions
        "time_zone": "lst_ldt",  # local time at the station, DST-aware
        "units": "metric",
        "interval": "hilo",  # only the turning points, not every 6 minutes
        "format": "json",
    }

    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(
                settings.noaa_tides_api_url,
                params=params,
                headers={"User-Agent": settings.http_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tide lookup failed for station %s: %s", station["id"], exc)
        return None

    tide = _parse_predictions(payload, now)
    if tide is None:
        return None

    tide.station_id = station["id"]
    tide.station_name = station["name"]
    tide.station_distance_km = round(distance_km, 1)

    # Wave and sea-temperature context is a nice-to-have; a failure here must
    # not discard the tide data we already have.
    marine = _fetch_marine(latitude, longitude)
    if marine:
        tide.wave_height_m = marine.get("wave_height")
        tide.sea_surface_temperature_c = marine.get("sea_surface_temperature")

    return tide


def _parse_predictions(payload: dict[str, Any], now: datetime) -> TideConditions | None:
    """Extract the next high and low tide, and infer the current trend.

    The trend is the actionable part. NOAA gives us a sequence of alternating
    H and L turning points; whichever comes next tells us which way the water
    is currently moving. If the next event is a high tide, the tide is rising.
    """
    raw = payload.get("predictions")
    if not raw:
        # NOAA signals bad station/date combinations with an `error` object.
        if "error" in payload:
            logger.warning("NOAA tide API error: %s", payload["error"])
        return None

    events: list[TideEvent] = []
    for entry in raw:
        # "H"/"L", and "HH"/"LL" (higher high, lower low) at mixed-tide stations.
        kind = {"H": "high", "L": "low"}.get(str(entry.get("type", ""))[:1])
        if kind is None:
            continue
        try:
            when = datetime.strptime(entry["t"], "%Y-%m-%d %H:%M")
            events.append(TideEvent(time=when, height_m=float(entry["v"]), kind=kind))
        except (KeyError, ValueError):
            continue

    if not events:
        return None

    events.sort(key=lambda e: e.time)
    future = [e for e in events if e.time >= now]

    next_high = next((e.time for e in future if e.kind == "high"), None)
    next_low = next((e.time for e in future if e.kind == "low"), None)

    trend: str | None = None
    if future:
        # The very next turning point determines the direction of travel.
        trend = "rising" if future[0].kind == "high" else "falling"

    # Indicative only: good enough to say "near low water", not to navigate by.
    water_level = tide_height_at(events, now)

    return TideConditions(
        water_level_m=round(water_level, 2) if water_level is not None else None,
        trend=trend,
        next_high_tide=next_high,
        next_low_tide=next_low,
        retrieved_at=datetime.now(),
        events=events,
    )


def tide_height_at(events: Sequence[TideEvent], moment: datetime) -> float | None:
    """Predicted height at `moment`, from the turning points either side of it.

    A half-cosine between consecutive high and low water: the water moves
    slowest at the turn and fastest midway, as a real tide does. Many NOAA
    stations (the subordinate ones, typical of small harbours and sloughs)
    publish only highs and lows, so this is the curve every station supports.
    None outside the span of `events`.
    """
    ordered = sorted(events, key=lambda e: e.time)
    for before, after in zip(ordered, ordered[1:], strict=False):
        if before.time <= moment <= after.time:
            span = (after.time - before.time).total_seconds()
            if span <= 0:
                return before.height_m
            fraction = (moment - before.time).total_seconds() / span
            eased = (1 - math.cos(math.pi * fraction)) / 2
            return before.height_m + (after.height_m - before.height_m) * eased
    return None


def tide_curve(
    events: Sequence[TideEvent],
    start: datetime,
    end: datetime,
    step: timedelta = timedelta(minutes=15),
) -> list[tuple[datetime, float]]:
    """Heights every `step` from `start` to `end` inclusive.

    Empty unless the events span the whole range: half a curve, ending where
    the predictions run out, would read as the water stopping.
    """
    points: list[tuple[datetime, float]] = []
    moment = start
    while moment <= end:
        height = tide_height_at(events, moment)
        if height is None:
            return []
        points.append((moment, round(height, 3)))
        moment += step
    return points


def _fetch_marine(latitude: float, longitude: float) -> dict[str, float] | None:
    """Current wave height and sea surface temperature, or None."""
    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(
                settings.marine_api_url,
                params={
                    "latitude": f"{latitude:.4f}",
                    "longitude": f"{longitude:.4f}",
                    "current": "wave_height,sea_surface_temperature",
                    "timezone": "auto",
                },
                headers={"User-Agent": settings.http_user_agent},
            )
            response.raise_for_status()
            current = response.json().get("current", {}) or {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Marine conditions unavailable for (%s, %s): %s", latitude, longitude, exc)
        return None

    return {
        key: current[key]
        for key in ("wave_height", "sea_surface_temperature")
        if current.get(key) is not None
    }


def describe_tide(tide: TideConditions | None, now: datetime | None = None) -> str:
    """One plain-language sentence about the tide, for prompts and reports.

    This string goes straight into the assessment prompt and the incident
    report, so it is written to be read by a volunteer, not parsed by a model.
    `now` is the moment the sentence describes: a stored snapshot passes the
    time it was taken, so "low water in 5h" is not re-measured from today.
    """
    if tide is None:
        return "Tide data unavailable for this location."

    parts: list[str] = []

    if tide.trend == "rising" and tide.next_high_tide:
        hours = _hours_until(tide.next_high_tide, now)
        parts.append(
            f"Tide is RISING, high water in about {hours}. "
            "Water is advancing toward the animal and may refloat it."
        )
    elif tide.trend == "falling" and tide.next_low_tide:
        hours = _hours_until(tide.next_low_tide, now)
        parts.append(
            f"Tide is FALLING, low water in about {hours}. "
            "The animal will be left further from the water as time passes."
        )
    elif tide.trend:
        parts.append(f"Tide is {tide.trend}.")

    if tide.wave_height_m is not None:
        parts.append(f"Wave height {tide.wave_height_m:.1f} m.")
    if tide.sea_surface_temperature_c is not None:
        parts.append(f"Sea temperature {tide.sea_surface_temperature_c:.1f} C.")
    if tide.station_name:
        parts.append(
            f"(Station: {tide.station_name}, {tide.station_distance_km} km away.)"
        )

    return " ".join(parts)


def _hours_until(moment: datetime, now: datetime | None = None) -> str:
    """Format a future time as "2h 15m", for human-readable tide windows."""
    delta = moment - (now or datetime.now())
    total_minutes = max(int(delta.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"
