"""Validate aggregate evidence without treating a cell center as a flight target."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifejacket.models.drone import DroneMissionRequest
from lifejacket.models.tables import HistoricalStrandingCellRow, HistoricalStrandingDatasetRow
from lifejacket.services.historical_strandings import GRID_DEGREES, MIN_PUBLIC_CELL_COUNT


def validate_historical_context(mission: DroneMissionRequest, session: Session) -> None:
    """Recheck provenance at planning and execution; synthetic demos need no DB query."""
    context = mission.historical_context
    if context is None:
        return
    dataset = session.get(HistoricalStrandingDatasetRow, context.dataset_id)
    if dataset is None or dataset.sha256 != context.dataset_sha256:
        raise ValueError(
            "Historical dataset changed or is unavailable; reload density and review"
        )
    cell = session.scalar(select(HistoricalStrandingCellRow).where(
        HistoricalStrandingCellRow.dataset_id == context.dataset_id,
        HistoricalStrandingCellRow.latitude_index == context.latitude_index,
        HistoricalStrandingCellRow.longitude_index == context.longitude_index,
        HistoricalStrandingCellRow.count >= MIN_PUBLIC_CELL_COUNT,
    ))
    if cell is None:
        raise ValueError("Selected historical cell is unavailable at the public threshold")
    south = context.latitude_index * GRID_DEGREES
    west = context.longitude_index * GRID_DEGREES
    area = mission.survey_area
    epsilon = 1e-9  # tolerate binary representation at the grid boundary
    if not (
        south - epsilon <= area.south < area.north <= south + GRID_DEGREES + epsilon
        and west - epsilon <= area.west < area.east <= west + GRID_DEGREES + epsilon
    ):
        raise ValueError("Choose a smaller survey area inside the selected historical cell")
