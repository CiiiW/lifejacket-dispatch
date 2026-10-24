"""Historical evidence gates using synthetic aggregate fixtures, never private NOAA rows."""

import pytest
from fastapi.testclient import TestClient
from lifejacket.api.main import app
from lifejacket.drones.planner import demo_mission
from lifejacket.models.db import get_session
from lifejacket.models.tables import (
    Base,
    HistoricalStrandingCellRow,
    HistoricalStrandingDatasetRow,
    IncidentRow,
)
from lifejacket.services.historical_strandings import DATASET_ID
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def historical_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as session:
        session.add(HistoricalStrandingDatasetRow(
            dataset_id=DATASET_ID, sha256="a" * 64, total_records=25,
            included_records=25, exclusions_json={},
        ))
        session.flush()
        session.add(HistoricalStrandingCellRow(
            dataset_id=DATASET_ID, latitude_index=368, longitude_index=-1218, count=25,
        ))

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        yield TestClient(app), sessions
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def mission_with_context():
    mission = demo_mission().model_dump()
    mission["historical_context"] = dict(
        dataset_id=DATASET_ID, dataset_sha256="a" * 64,
        latitude_index=368, longitude_index=-1218,
    )
    return mission


def test_density_to_reviewed_mock_flight_without_creating_incidents(historical_api):
    client, sessions = historical_api
    density = client.get("/historical-strandings/density").json()
    assert density["dataset_sha256"] == "a" * 64
    assert density["cells"] == [dict(latitude=36.85, longitude=-121.75, band="25-99")]
    mission = mission_with_context()
    response = client.post("/drones/plan", json=mission)
    assert response.status_code == 200
    plan = response.json()
    assert plan["status"] == "ready_for_review"
    assert plan["synthetic"] is True
    assert plan["mission"]["historical_context"] == mission["historical_context"]
    run = client.post("/drones/simulate", json=dict(
        mission=mission, plan_id=plan["plan_id"], reviewed_by="Test coordinator",
    ))
    assert run.status_code == 200 and run.json()["status"] == "completed"
    with sessions() as session:
        assert session.scalar(select(IncidentRow)) is None


@pytest.mark.parametrize("kind", ["stale", "missing", "sparse", "outside"])
def test_unusable_historical_context_is_rejected(historical_api, kind):
    client, sessions = historical_api
    mission = mission_with_context()
    if kind == "stale":
        mission["historical_context"]["dataset_sha256"] = "b" * 64
    elif kind == "missing":
        mission["historical_context"]["latitude_index"] = 369
    elif kind == "sparse":
        with sessions.begin() as session:
            session.scalar(select(HistoricalStrandingCellRow)).count = 9
    else:
        mission["survey_area"]["west"] = -121.801
    assert client.post("/drones/plan", json=mission).status_code == 409


def test_reimport_invalidates_review_and_new_provenance_changes_plan_id(historical_api):
    client, sessions = historical_api
    mission = mission_with_context()
    original = client.post("/drones/plan", json=mission).json()
    with sessions.begin() as session:
        session.get(HistoricalStrandingDatasetRow, DATASET_ID).sha256 = "b" * 64
    payload = dict(mission=mission, plan_id=original["plan_id"], reviewed_by="Reviewer")
    assert client.post("/drones/simulate", json=payload).status_code == 409
    mission["historical_context"]["dataset_sha256"] = "b" * 64
    new = client.post("/drones/plan", json=mission).json()
    assert new["plan_id"] != original["plan_id"]
    assert client.post("/drones/simulate", json=payload).status_code == 409


def test_threshold_and_plan_constraints_still_apply(historical_api):
    client, sessions = historical_api
    with sessions.begin() as session:
        session.scalar(select(HistoricalStrandingCellRow)).count = 10
    mission = mission_with_context()
    mission["simulated_wind_mps"] = 12
    plan = client.post("/drones/plan", json=mission).json()
    assert plan["status"] == "blocked"
    assert client.post("/drones/simulate", json=dict(
        mission=mission, plan_id=plan["plan_id"], reviewed_by="Reviewer",
    )).status_code == 409
