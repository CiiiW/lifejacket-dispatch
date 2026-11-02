"""Persistence for demo frame review only; no dispatch, analysis or case linking."""

from datetime import UTC, datetime

from sqlalchemy import update

from lifejacket.models.tables import DroneDemoFrameRow


def frame_out(row):
    return {
        "demo_id": row.demo_id,
        "demo_only": True,
        "status": row.status,
        "revision": row.revision,
        "metadata": row.metadata_json,
        "photo_url": f"/drone-demo/frames/{row.demo_id}/photo",
        "reviews": row.reviews_json,
        "aircraft_position": None,
        "animal_position": None,
        "incident_id": None,
        "created_at": row.created_at.isoformat(),
    }


def review(session, row, body):
    entry = {
        "actor": body.actor,
        "decision": body.decision,
        "note": body.note,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    result = session.execute(
        update(DroneDemoFrameRow)
        .where(
            DroneDemoFrameRow.demo_id == row.demo_id,
            DroneDemoFrameRow.revision == body.expected_revision,
        )
        .values(
            status=body.decision,
            revision=body.expected_revision + 1,
            reviews_json=[*row.reviews_json, entry],
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise ValueError("Demo review changed; refresh before saving")
    session.commit()
    session.refresh(row)
    return frame_out(row)
