"""Live conditions for the console, and the tide curve behind its chart.

The stored snapshot is what the agents saw when a report came in; a
coordinator opening the case later gets the same display model fetched now.
No network: the context lookups are replaced with a fixed one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from lifejacket.api import conditions as conditions_module
from lifejacket.api.conditions import build_conditions
from lifejacket.api.main import app
from lifejacket.context.tides import _parse_predictions, tide_curve, tide_height_at
from lifejacket.models.db import get_session
from lifejacket.models.schemas import EnvironmentalContext, GeoPoint, TideConditions, TideEvent
from lifejacket.models.tables import Base, IncidentRow
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DAY = datetime(2026, 11, 24)


def turns(day: datetime = DAY) -> list[TideEvent]:
    """A plausible semidiurnal day, with a turn before and after midnight."""
    spec = [(-5.5, 0.4, "low"), (0.9, 1.7, "high"), (7.1, 0.3, "low"),
            (13.3, 1.6, "high"), (19.6, 0.5, "low"), (25.8, 1.8, "high")]
    return [TideEvent(time=day + timedelta(hours=h), height_m=m, kind=k) for h, m, k in spec]


def context_at(moment: datetime, events: list[TideEvent] | None = None) -> EnvironmentalContext:
    events = turns(datetime.combine(moment.date(), datetime.min.time())) if events is None else events
    upcoming = [e for e in events if e.time >= moment]
    tide = TideConditions(
        station_name="Elkhorn Slough, Highway 1 Bridge",
        station_distance_km=0.4,
        trend="rising" if upcoming[0].kind == "high" else "falling",
        next_high_tide=next(e.time for e in upcoming if e.kind == "high"),
        next_low_tide=next(e.time for e in upcoming if e.kind == "low"),
        water_level_m=round(tide_height_at(events, moment), 2),
        events=events,
    )
    return EnvironmentalContext(
        location=GeoPoint(latitude=36.8097, longitude=-121.79, place_name="Moss Landing"),
        weather=None,
        tide=tide,
        is_coastal=True,
        local_time=moment,
        unavailable=["weather"],
    )


def test_tide_height_eases_between_turns_like_a_real_tide():
    low, high = TideEvent(time=DAY, height_m=0.2, kind="low"), TideEvent(
        time=DAY + timedelta(hours=6), height_m=1.8, kind="high"
    )
    assert tide_height_at([low, high], DAY) == pytest.approx(0.2)
    assert tide_height_at([low, high], DAY + timedelta(hours=6)) == pytest.approx(1.8)
    assert tide_height_at([low, high], DAY + timedelta(hours=3)) == pytest.approx(1.0)
    # Slow near the turn, fast midway: the first hour covers far less than a
    # sixth of the range, which a straight line between the turns would not.
    assert tide_height_at([low, high], DAY + timedelta(hours=1)) < 0.2 + 1.6 / 6
    assert tide_height_at([low, high], DAY - timedelta(minutes=1)) is None


def test_curve_covers_the_whole_day_or_nothing():
    curve = tide_curve(turns(), DAY, DAY + timedelta(days=1))
    assert len(curve) == 97  # every 15 minutes, midnight to midnight
    assert curve[0][0] == DAY and curve[-1][0] == DAY + timedelta(days=1)
    heights = [h for _, h in curve]
    assert min(heights) >= 0.3 and max(heights) <= 1.8
    # Predictions that stop before the day ends draw nothing, not half a day.
    assert tide_curve(turns()[:4], DAY, DAY + timedelta(days=1)) == []


def test_every_turn_is_kept_and_mixed_tide_codes_are_read():
    payload = {"predictions": [
        {"t": "2026-11-24 00:54", "v": "1.701", "type": "HH"},
        {"t": "2026-11-24 07:06", "v": "0.312", "type": "L"},
        {"t": "2026-11-24 13:18", "v": "1.598", "type": "H"},
        {"t": "2026-11-24 19:36", "v": "0.103", "type": "LL"},
    ]}
    tide = _parse_predictions(payload, DAY + timedelta(hours=9))
    assert [e.kind for e in tide.events] == ["high", "low", "high", "low"]
    assert tide.trend == "rising"
    assert tide.next_high_tide == datetime(2026, 11, 24, 13, 18)
    assert tide.next_low_tide == datetime(2026, 11, 24, 19, 36)


def test_a_snapshot_describes_its_own_moment_not_today():
    reported = DAY + timedelta(hours=10)  # long past: the wall clock would say "0m"
    shown = build_conditions(context_at(reported))
    assert shown.live is False
    assert shown.local_time == reported
    assert "RISING, high water in about 3h 18m" in shown.tide_summary
    # The chart is the report's day, with its highs and lows.
    assert shown.tide_curve[0].time == DAY and len(shown.tide_curve) == 97
    assert [e.kind for e in shown.tide_events][:2] == ["low", "high"]
    assert shown.tide_station_distance_km == 0.4


def test_an_old_snapshot_without_turns_simply_has_no_chart():
    shown = build_conditions(context_at(DAY + timedelta(hours=10), events=turns()).model_copy(
        update={"tide": TideConditions(trend="falling")}
    ))
    assert shown.tide_curve == [] and shown.tide_events == []


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(conditions_module, "_live_cache", {})
    calls: list[GeoPoint] = []

    def fake_gather(location: GeoPoint) -> EnvironmentalContext:
        calls.append(location)
        return context_at(datetime.now())

    monkeypatch.setattr(conditions_module, "gather_context", fake_gather)
    with sessions() as session:
        session.add(IncidentRow(incident_id="otter", status="accepted", latitude=36.8097,
                                longitude=-121.79, place_name="Moss Landing"))
        session.add(IncidentRow(incident_id="nowhere", status="intake"))
        session.commit()
    yield TestClient(app), calls
    app.dependency_overrides.clear()


def test_live_conditions_are_fetched_now_and_reused_briefly(api):
    client, calls = api
    first = client.get("/incidents/otter/conditions")
    assert first.status_code == 200
    body = first.json()
    assert body["live"] is True
    assert len(body["tide_curve"]) == 97
    assert body["tide_curve"][0]["time"].startswith(datetime.now().date().isoformat())
    assert calls[0].latitude == 36.8097 and calls[0].place_name == "Moss Landing"

    assert client.get("/incidents/otter/conditions").json() == body
    assert len(calls) == 1  # the second open reused the ten-minute reading


def test_live_conditions_need_a_known_incident_with_a_location(api):
    client, calls = api
    assert client.get("/incidents/missing/conditions").status_code == 404
    assert client.get("/incidents/nowhere/conditions").status_code == 409
    assert calls == []
