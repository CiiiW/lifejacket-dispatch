"""FastAPI application: the HTTP surface for both client apps.

Deliberately thin. Routes parse requests, call into `services/` or
`dispatch/`, and serialise the result. **No business logic lives here** -- if
you find yourself reasoning about severity or species in a route handler, it
belongs in the relevant package instead.

Two clients share this API:

- `clients/reporter_app` -- the public's phone app (intake, chat, map).
- `clients/responder_console` -- rescue organisations, on phone and web.

Run it with:

    uvicorn lifejacket.api.main:app --reload --app-dir backend

Interactive docs are then at http://localhost:8000/docs, which is the fastest
way to explore the API without writing any client code.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lifejacket.api.routes import coordination, incidents, intake, responders
from lifejacket.config import settings
from lifejacket.models.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create tables and the photo directory before serving any request."""
    init_db()
    settings.photo_storage_dir.mkdir(parents=True, exist_ok=True)
    logger.info("LifeJacket ready. Database: %s", settings.database_url)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="LifeJacket Dispatch",
    description=(
        "Agentic AI dispatch for stranded and injured wild animals. "
        "A member of the public photographs an animal; the system identifies it, "
        "assesses the situation against tide and weather, and routes a report to "
        "the nearest permitted rescue organisation."
    ),
    version="2.0.0",
)

# The phone apps are not served from this origin, so CORS is required. Lock
# `cors_allow_origins` down to the real client origins before deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intake.router)
app.include_router(incidents.router)
app.include_router(responders.router)
app.include_router(coordination.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Liveness check for deployment platforms."""
    return {"status": "ok"}
