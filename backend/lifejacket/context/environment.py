"""Assembling everything we know about the scene around the animal.

One function, `gather_context`, calls weather, tides, and geocoding and packs
the results into an `EnvironmentalContext`. The assessment agent takes that
object and nothing else about the location.

The design rule throughout: **partial context is normal and must work.** Any
of the three lookups can fail, and a rescue cannot wait for NOAA to come back
up. Failures are recorded by name in `unavailable` so the downstream prompt can
be explicit about what was not checked.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from lifejacket.context.geocode import reverse_geocode
from lifejacket.context.tides import describe_tide, fetch_tides
from lifejacket.context.weather import fetch_weather, weather_risk_score
from lifejacket.models.schemas import EnvironmentalContext, GeoPoint

logger = logging.getLogger(__name__)


def gather_context(location: GeoPoint) -> EnvironmentalContext:
    """Collect weather, tide, and place information for an incident location.

    The three lookups are independent HTTP calls, so they run concurrently --
    together they take as long as the slowest one (about a second) rather than
    the sum. This is on the critical path of a live report, so it is worth the
    small amount of threading complexity.
    """
    latitude, longitude = location.latitude, location.longitude

    with ThreadPoolExecutor(max_workers=3) as pool:
        weather_future = pool.submit(fetch_weather, latitude, longitude)
        tide_future = pool.submit(fetch_tides, latitude, longitude)
        place_future = pool.submit(reverse_geocode, latitude, longitude)

        weather = weather_future.result()
        tide = tide_future.result()
        place = place_future.result()

    unavailable: list[str] = []
    if weather is None:
        unavailable.append("weather")
    if tide is None:
        # Absence of tide data has two very different causes, and the
        # distinction changes how the report should read.
        unavailable.append("tide")
    if place is None:
        unavailable.append("place_name")

    # Fill in the place name if the reporter did not supply one.
    resolved_location = location.model_copy()
    if place and not resolved_location.place_name:
        resolved_location.place_name = place.display_name

    return EnvironmentalContext(
        location=resolved_location,
        weather=weather,
        tide=tide,
        # No tide station within range is our proxy for "not on the coast".
        # Inland incidents are real (a stranded deer, a bird) but tide
        # reasoning should not be applied to them.
        is_coastal=tide is not None,
        local_time=datetime.now(),
        unavailable=unavailable,
    )


def summarise_for_prompt(context: EnvironmentalContext) -> str:
    """Render the context as the text block the assessment agent reads.

    Written as prose rather than JSON because the model reasons better over a
    description than over a nested object, and because this same text is close
    to what a human coordinator would want to read.
    """
    lines: list[str] = []

    location = context.location
    where = location.place_name or "an unnamed location"
    lines.append(
        f"LOCATION: {where} "
        f"({location.latitude:.4f}, {location.longitude:.4f}), "
        f"reported via {location.source}."
    )

    if context.local_time:
        lines.append(
            f"LOCAL TIME: {context.local_time:%Y-%m-%d %H:%M} "
            f"({context.local_time:%A})"
        )

    lines.append(f"TIDE: {describe_tide(context.tide)}")

    weather = context.weather
    if weather is None:
        lines.append("WEATHER: unavailable -- do not assume conditions are calm.")
    else:
        bits: list[str] = []
        if weather.condition:
            bits.append(weather.condition)
        if weather.temperature_c is not None:
            bits.append(f"{weather.temperature_c:.0f} C")
        if weather.wind_speed_mph is not None:
            gust = (
                f" (gusting {weather.wind_gust_mph:.0f})"
                if weather.wind_gust_mph is not None
                else ""
            )
            bits.append(f"wind {weather.wind_speed_mph:.0f} mph{gust}")
        if weather.precipitation_probability is not None:
            bits.append(f"{weather.precipitation_probability:.0%} chance of precipitation")
        if weather.visibility_miles is not None:
            bits.append(f"visibility {weather.visibility_miles:.1f} miles")
        lines.append("WEATHER: " + ", ".join(bits))

        risk = weather_risk_score(weather)
        lines.append(
            f"RESPONDER CONDITIONS RISK: {risk:.2f} "
            "(0 = straightforward, 1.5 = hazardous for responders)"
        )

        if weather.sunset_local:
            remaining = weather.sunset_local - (context.local_time or datetime.now())
            hours_left = remaining.total_seconds() / 3600
            if 0 < hours_left < 3:
                lines.append(
                    f"DAYLIGHT: sunset at {weather.sunset_local:%H:%M}, "
                    f"only {hours_left:.1f} hours of light left."
                )

    if not context.is_coastal:
        lines.append(
            "COASTAL: no tide station within range -- treat this as an inland "
            "location and do not reason about tides."
        )

    if context.unavailable:
        lines.append(
            "DATA GAPS: " + ", ".join(context.unavailable)
            + ". State these as unknown in your output rather than guessing."
        )

    return "\n".join(lines)
