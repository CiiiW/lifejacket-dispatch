"""Private, standalone public-photo review app; never creates dispatch records."""

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from lifejacket.config import REPO_ROOT
from lifejacket.models.schemas import AnimalGroup
from lifejacket.research.condition_baseline import BaselineStore, Conflict, HumanReview, Target
from lifejacket.taxonomy import GROUP_LABELS


class Rerun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_prediction_id: str | None = None


def create_app(store: BaselineStore):
    app = FastAPI(
        title="LifeJacket • Public photo development review", docs_url=None, redoc_url=None
    )

    @app.exception_handler(Conflict)
    async def conflict(request: Request, exc: Conflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LookupError)
    async def missing(request: Request, exc: LookupError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/")
    def index():
        return FileResponse(REPO_ROOT / "research/public_condition_pilot/review.html")

    @app.get("/api/summary")
    def summary():
        return {
            **store.summary(),
            "run_id": store.meta["run_id"],
            "groups": {g.value: GROUP_LABELS.get(g, "Unknown animal") for g in AnimalGroup},
        }

    @app.get("/api/cases")
    def cases():
        return [
            {
                "case_id": key,
                "status": (store.prediction(key) or {}).get("status", "not_run"),
                "reviewed": bool(store.review(key)),
            }
            for key in store.rows
        ]

    @app.get("/api/cases/{key}")
    def case(key: str):
        return store.case(key)

    @app.get("/api/cases/{key}/photo")
    def photo(key: str):
        return FileResponse(store.image_path(key), headers={"Cache-Control": "no-store"})

    @app.post("/api/cases/{key}/analyze")
    def analyze(key: str, target: Target):
        return store.analyze(key, target)

    @app.post("/api/cases/{key}/rerun")
    def rerun(key: str, body: Rerun):
        return store.analyze(key, expected_prediction_id=body.expected_prediction_id)

    @app.post("/api/cases/{key}/review")
    def review(key: str, body: HumanReview):
        return store.save_review(key, body)

    @app.get("/api/export")
    def export():
        return JSONResponse(
            {
                "run": store.meta,
                "summary": store.summary(),
                "cases": [store.case(key) for key in store.rows],
            },
            headers={"Content-Disposition": 'attachment; filename="condition-review.json"'},
        )

    return app
