"""Weather at the incident location, from Open-Meteo.

Why Open-Meteo rather than the US National Weather Service: it is global and
keyless. The prototype's NWS client worked well but only covers US territory,
and it also shipped with a `PlaceholderWeatherProvider` that fabricated
plausible numbers from arithmetic on the coordinates. That provider was the
default, which meant demos showed invented weather that looked real.

The rule this module follows instead: **if the API fails, say so.** A failed
call returns `None` and records the failure in
`EnvironmentalContext.unavailable`, so the incident report reads "weather
unavailable" rather than implying calm conditions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from lifejacket.config import load_scoring_config, settings
from lifejacket.models.schemas import WeatherConditions

logger = logging.getLogger(__name__)

#: Open-Meteo WMO weather codes, collapsed to the words our risk model looks
#: for. Full table: https://open-meteo.com/en/docs
_WMO_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def fetch_weather(latitude: float, longitude: float) -> WeatherConditions | None:
    """Current conditions at a point. Returns None if the API is unreachable.

    Requests imperial units for wind and visibility because the responders are
    US-based stranding networks who work in miles per hour; temperature stays
    metric to match the marine data.
    """
    params = {
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "current": (
            "temperature_2m,precipitation,weather_code,"
            "wind_speed_10m,wind_gusts_10m,visibility"
        ),
        "hourly": "precipitation_probability",
        "daily": "sunset",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "forecast_days": "1",
    }

    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(
                settings.weather_api_url,
                params=params,
                headers={"User-Agent": settings.http_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Weather lookup failed for (%s, %s): %s", latitude, longitude, exc)
        return None

    return _parse_weather(payload)


def _parse_weather(payload: dict[str, Any]) -> WeatherConditions:
    """Turn an Open-Meteo response into our own model.

    Every field is read defensively: the API occasionally omits `visibility`
    for some grid points, and a missing field must not break intake.
    """
    current = payload.get("current", {}) or {}

    weather_code = current.get("weather_code")
    condition = _WMO_CODE_DESCRIPTIONS.get(weather_code) if weather_code is not None else None

    # Visibility arrives in metres; responders think in miles.
    visibility_m = current.get("visibility")
    visibility_miles = visibility_m / 1609.344 if visibility_m is not None else None

    return WeatherConditions(
        temperature_c=current.get("temperature_2m"),
        wind_speed_mph=current.get("wind_speed_10m"),
        wind_gust_mph=current.get("wind_gusts_10m"),
        precipitation_probability=_next_hour_precip_probability(payload),
        visibility_miles=visibility_miles,
        condition=condition,
        sunset_local=_first_datetime(payload.get("daily", {}).get("sunset")),
        retrieved_at=datetime.now(),
    )


def _next_hour_precip_probability(payload: dict[str, Any]) -> float | None:
    """Precipitation chance for the coming hour, as a 0-1 fraction.

    Open-Meteo returns an array covering the whole forecast window starting at
    midnight local time. We want the first value at or after now, since a 40%
    chance of rain at 3am does not affect a rescue happening at noon.
    """
    hourly = payload.get("hourly", {}) or {}
    times = hourly.get("time") or []
    values = hourly.get("precipitation_probability") or []
    if not times or not values:
        return None

    now = datetime.now()
    # strict=False: the two arrays should be the same length, but a short one
    # means a truncated response, and pairing what we have beats raising.
    for timestamp, value in zip(times, values, strict=False):
        try:
            if datetime.fromisoformat(timestamp) >= now and value is not None:
                return value / 100.0
        except (ValueError, TypeError):
            continue

    # All forecast hours are in the past (stale response); fall back to the
    # last known value rather than reporting nothing.
    return values[-1] / 100.0 if values[-1] is not None else None


def _first_datetime(values: list[str] | None) -> datetime | None:
    if not values:
        return None
    try:
        return datetime.fromisoformat(values[0])
    except (ValueError, TypeError):
        return None


def weather_risk_score(weather: WeatherConditions | None) -> float:
    """How much the weather complicates a rescue, as an additive score.

    Ported from the team's prototype (`archive/agent2_reference.ipynb`) with the
    thresholds moved out to `config/scoring.json` so they can be tuned without
    editing code.

    This score does **not** describe danger to the animal -- it describes
    difficulty and risk for the people responding. High wind and poor
    visibility mean a volunteer should not go alone to a remote beach.

    Returns:
        A score from 0.0 upwards, capped by `weather_risk.max_score`.
    """
    if weather is None:
        # Unknown weather is not the same as good weather, but inventing risk
        # would be worse. The report states the gap; the score stays neutral.
        return 0.0

    cfg = load_scoring_config()["weather_risk"]
    score = 0.0

    wind = weather.wind_speed_mph
    if wind is not None:
        if wind >= cfg["wind_speed_mph_risk"]:
            score += 0.6
        if wind >= cfg["wind_speed_mph_high_risk"]:
            score += 0.4  # cumulative with the above: strong wind scores both

    precip = weather.precipitation_probability
    if precip is not None and precip >= cfg["precipitation_probability_risk"]:
        score += 0.5

    visibility = weather.visibility_miles
    if visibility is not None and visibility < cfg["visibility_miles_risk"]:
        score += 0.5

    if weather.condition:
        condition_lower = weather.condition.lower()
        if any(term in condition_lower for term in cfg["condition_terms"]):
            score += 0.4

    return min(score, cfg["max_score"])
