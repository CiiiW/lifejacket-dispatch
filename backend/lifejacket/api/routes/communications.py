"""The console's Communications tab: every conversation with a reporter.

    GET /communications/threads   threads, replies owed first

A legacy console route like the rest of the local console (no sign-in;
network mode blocks it with every other legacy route). Reading and writing a
single thread stays where it was: `/incidents/{id}/messages`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lifejacket.models.coordinator import ThreadSummary
from lifejacket.models.db import get_session
from lifejacket.services import reporter_thread

router = APIRouter(prefix="/communications", tags=["communications (console)"])


@router.get("/threads", response_model=list[ThreadSummary])
def threads(session: Session = Depends(get_session)) -> list[ThreadSummary]:
    return reporter_thread.thread_summaries(session)
