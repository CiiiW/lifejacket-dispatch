"""Database engine and session management.

Usage in application code is always the context manager:

    from lifejacket.models.db import session_scope

    with session_scope() as session:
        session.add(row)

It commits on success and rolls back on any exception, so a half-written
incident never survives an error.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from lifejacket.config import settings
from lifejacket.models.tables import Base


def _make_engine():
    """Build the engine, with the one SQLite-specific tweak we need.

    SQLite refuses connections shared across threads by default, and FastAPI
    serves requests from a thread pool. `check_same_thread=False` lifts that
    restriction; it is safe here because each request takes its own session.
    """
    kwargs: dict = {"echo": False, "future": True}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.database_url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create any missing tables.

    Fine for a project at this stage. Once the schema is stable and there is
    real data to preserve, switch to Alembic migrations -- `create_all` will
    never alter an existing table, so a changed column is silently ignored.
    """
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session (see `api.deps`)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
