"""Serve the built console and ONLY the demo API on loopback for private previews."""

import argparse
import re
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from lifejacket.api.routes.drone_demo import router
from lifejacket.config import settings
from lifejacket.models.db import init_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-dir", type=Path, default=Path("clients/responder_console/dist"))
    parser.add_argument("--port", type=int, default=8915)
    args = parser.parse_args()
    if not settings.drone_demo_enabled:
        parser.error("Set DRONE_DEMO_ENABLED=true for this private demo environment")
    index = args.web_dir / "index.html"
    if not index.is_file():
        parser.error("Build the web console first")
    # Relative asset URLs retain Jupyter's authenticated /proxy/<port>/ prefix.
    page = re.sub(r'(src|href)="/(?!/)', r'\1="./', index.read_text())

    @asynccontextmanager
    async def lifespan(_):
        init_db()
        yield

    app = FastAPI(lifespan=lifespan)
    api = FastAPI()
    api.include_router(router)
    app.mount("/api", api)

    @app.get("/", response_class=HTMLResponse)
    def home():
        return page

    app.mount("/", StaticFiles(directory=args.web_dir), name="console")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
