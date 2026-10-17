"""The public map must never reveal original stranding locations or small cells."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lifejacket.api.main import app
from lifejacket.models.db import get_session
from lifejacket.models.tables import Base, HistoricalStrandingCellRow
from lifejacket.services.historical_strandings import import_workbook


def _workbook(path, counts=(11, 2)):
    book = Workbook()
    sheet = book.active
    sheet.append(["State", "Latitude", "Longitude", "Latitude Units", "Longitude Units",
                  "Observation Date", "Confidence Code", "Locality Detail", "Additional Remarks"])
    for count, latitude in zip(counts, (36.81, 37.81)):
        for _ in range(count):
            sheet.append(["CA", latitude, -121.79, "decimal degrees", "decimal degrees",
                          datetime(2015, 1, 1), "Confirmed - High Report", "private location", "private text"])
    sheet.append(["CA", 36.8, -121.79, "decimal degrees", "decimal degrees",
                  datetime(2015, 1, 1), "Unconfirmed", "private", "private"])
    sheet.append(["CA", "36.88.449", "121.83.255", "deg/min/sec", "deg/min/sec",
                  datetime(2015, 1, 1), "Confirmed", "private", "private"])
    sheet.append(["CA", 40.574132, -73.9724017, "decimal degrees", "decimal degrees",
                  datetime(2015, 1, 1), "Confirmed", "private", "private"])
    sheet.append(["CA", 36.8, -121.79, "decimal degrees", "decimal degrees",
                  datetime(2015, 1, 1), None, "private", "private"])
    book.save(path)


def test_private_import_and_public_threshold(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def override():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app)
        assert client.get("/historical-strandings/density").json()["available"] is False
        path = tmp_path / "private.xlsx"
        _workbook(path)
        with sessions.begin() as session:
            result = import_workbook(path, session)
        assert result["included"] == 13
        assert result["excluded"] == {
            "unconfirmed": 1, "invalid_or_nondecimal_coordinates": 1,
            "outside_california_bounds": 1, "unknown_confidence": 1,
        }
        response = client.get("/historical-strandings/density")
        assert response.status_code == 200
        assert response.json()["cells"] == [{"latitude": 36.85, "longitude": -121.75, "band": "10-24"}]
        assert "private" not in response.text

        # A repeat import replaces the old cells; a rejected workbook leaves
        # the previous aggregate intact.
        _workbook(path, counts=(25, 1))
        with sessions.begin() as session:
            import_workbook(path, session)
        assert client.get("/historical-strandings/density").json()["cells"][0]["band"] == "25-99"
        with sessions() as session:
            assert session.query(HistoricalStrandingCellRow).count() == 2
        path.unlink()
        with pytest.raises(FileNotFoundError), sessions.begin() as session:
            import_workbook(path, session)
        assert client.get("/historical-strandings/density").json()["available"] is True
    finally:
        app.dependency_overrides.clear()
