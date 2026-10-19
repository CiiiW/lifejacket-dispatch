"""Coarse, thresholded historical report density for the responder map."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.models.db import get_session
from lifejacket.models.tables import HistoricalStrandingCellRow, HistoricalStrandingDatasetRow
from lifejacket.services.historical_strandings import DATASET_ID, GRID_DEGREES

router = APIRouter(prefix="/historical-strandings", tags=["historical strandings"])
MIN_PUBLIC_CELL_COUNT = 10


class DensityCell(BaseModel):
    latitude: float
    longitude: float
    band: str  # 10-24 | 25-99 | 100+


class DensityResponse(BaseModel):
    available: bool
    label: str = "Historical stranding report density, 2006–2025"
    caveat: str = "Reports reflect observation effort and estimated locations; this is not stranding probability or a flight plan."
    grid_degrees: float = GRID_DEGREES
    min_reports_per_cell: int = MIN_PUBLIC_CELL_COUNT
    cells: list[DensityCell]


@router.get("/density", response_model=DensityResponse)
def density(session: Session = Depends(get_session)) -> DensityResponse:
    dataset = session.get(HistoricalStrandingDatasetRow, DATASET_ID)
    if dataset is None:
        return DensityResponse(available=False, cells=[])

    rows = session.scalars(
        select(HistoricalStrandingCellRow)
        .where(HistoricalStrandingCellRow.dataset_id == DATASET_ID)
        .where(HistoricalStrandingCellRow.count >= MIN_PUBLIC_CELL_COUNT)
    )
    return DensityResponse(available=True, cells=[
        DensityCell(
            latitude=round((row.latitude_index + 0.5) * GRID_DEGREES, 4),
            longitude=round((row.longitude_index + 0.5) * GRID_DEGREES, 4),
            band="100+" if row.count >= 100 else "25-99" if row.count >= 25 else "10-24",
        ) for row in rows
    ])
