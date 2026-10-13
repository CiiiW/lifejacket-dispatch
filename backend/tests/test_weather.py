"""Tests for the weather context the triage agent reads.

The daylight figure is the fiddly one: "0 minutes" has to mean "it is dark
now", at both ends of the night, and must never be confused with "unknown".
A responder reading "6 hours of light" when it is 2am would plan the wrong
response entirely.
"""

from __future__ import annotations

from datetime import datetime

from lifejacket.context.environment import summarise_for_prompt
from lifejacket.context.weather import minutes_to_sunset
from lifejacket.models.schemas import (
    EnvironmentalContext,
    GeoPoint,
    WeatherConditions,
)

SUNRISE = datetime(2026, 6, 1, 5, 47)
SUNSET = datetime(2026, 6, 1, 20, 23)


def _weather(**overrides) -> WeatherConditions:
    return WeatherConditions(
        **{
            "temperature_c": 14.0,
            "precipitation_mm": 0.0,
            "sunrise_local": SUNRISE,
            "sunset_local": SUNSET,
            **overrides,
        }
    )


class TestMinutesToSunset:
    def test_afternoon_counts_down_to_sunset(self):
        assert minutes_to_sunset(_weather(), datetime(2026, 6, 1, 19, 23)) == 60

    def test_after_sunset_is_zero_not_negative(self):
        assert minutes_to_sunset(_weather(), datetime(2026, 6, 1, 22, 0)) == 0

    def test_before_sunrise_is_also_zero(self):
        """2am is dark, even though sunset is still fifteen hours away."""
        assert minutes_to_sunset(_weather(), datetime(2026, 6, 1, 2, 0)) == 0

    def test_unknown_sunset_is_none_not_zero(self):
        """None means "we do not know", which is not the same as "it is dark"."""
        weather = WeatherConditions(temperature_c=14.0)
        assert minutes_to_sunset(weather, datetime(2026, 6, 1, 12, 0)) is None

    def test_missing_weather_is_none(self):
        assert minutes_to_sunset(None, datetime(2026, 6, 1, 12, 0)) is None

    def test_timezone_aware_sunset_does_not_raise(self):
        """Open-Meteo returns local wall-clock times; `now` here is naive."""
        from datetime import timedelta, timezone

        aware = _weather(
            sunset_local=SUNSET.replace(tzinfo=timezone(timedelta(hours=-7))),
            sunrise_local=SUNRISE.replace(tzinfo=timezone(timedelta(hours=-7))),
        )
        assert minutes_to_sunset(aware, datetime(2026, 6, 1, 19, 23)) == 60


class TestPromptSummary:
    """What the triage agent actually reads."""

    def _context(self, weather, local_time):
        return EnvironmentalContext(
            location=GeoPoint(latitude=36.8, longitude=-121.79, source="device_gps"),
            weather=weather,
            local_time=local_time,
        )

    def test_temperature_precipitation_and_daylight_all_appear(self):
        summary = summarise_for_prompt(
            self._context(
                _weather(temperature_c=11.5, precipitation_mm=4.2),
                datetime(2026, 6, 1, 19, 23),
            )
        )
        assert "12 C" in summary  # rounded for the prompt
        assert "4.2 mm precipitation falling now" in summary
        assert "DAYLIGHT: 60 minutes" in summary

    def test_dry_weather_says_so_explicitly(self):
        """Absence of rain is information; silence would be ambiguous."""
        summary = summarise_for_prompt(
            self._context(_weather(precipitation_mm=0.0), datetime(2026, 6, 1, 12, 0))
        )
        assert "no precipitation falling now" in summary

    def test_night_is_stated_as_already_dark(self):
        summary = summarise_for_prompt(
            self._context(_weather(), datetime(2026, 6, 1, 23, 30))
        )
        assert "already dark" in summary
        assert "DAYLIGHT: 0 minutes" in summary

    def test_unknown_sunset_warns_rather_than_implying_daylight(self):
        summary = summarise_for_prompt(
            self._context(
                WeatherConditions(temperature_c=14.0), datetime(2026, 6, 1, 12, 0)
            )
        )
        assert "do not assume daylight" in summary
