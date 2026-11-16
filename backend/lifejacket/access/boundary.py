"""Network mode exposes only reviewed endpoints; legacy routes fail closed."""

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from lifejacket.config import settings


class NetworkBoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if settings.network_auth_enabled:
            path = request.scope.get("path", "")
            safe = request.method in {"GET", "HEAD"} and (
                path == "/health" or path == "/access/me" or path.startswith("/network/")
            )
            # Dedicated reporter routes each enforce a draft key or a managed
            # phone identity. Never allow the raw legacy intake/photo endpoints.
            if (
                settings.reporter_phone_enabled
                and request.method == "POST"
                and re.fullmatch(
                    r"/reporter/(drafts|reports|drafts/[A-Za-z0-9_-]{1,40}/(turn|photo|submit)|reports/[A-Za-z0-9_-]{1,40}/(status|presence|contact-preferences))",
                    path,
                )
            ):
                safe = True
            if (
                settings.network_case_actions_enabled
                and request.method == "PATCH"
                and re.fullmatch(r"/network/cases/[A-Za-z0-9_-]{1,40}/response", path)
            ):
                safe = True
            if (
                settings.case_drone_requests_enabled
                and request.method in {"POST", "PATCH"}
                and re.fullmatch(
                    r"/network/cases/[A-Za-z0-9_-]{1,40}/drone-requests(?:/[a-f0-9]{32}(?:/(?:evidence(?:/[a-f0-9]{32}/(?:analysis|detector-result))?|monitoring|attention|reminders/retry|streams|streams/[a-f0-9]{32}/(?:capture|end)))?)?",
                    path,
                )
            ):
                safe = True
            # OPTIONS carries no case payload; the CORS layer validates the origin.
            if request.method != "OPTIONS" and not safe:
                return JSONResponse(
                    {"detail": "Endpoint unavailable in network mode"},
                    status_code=403,
                    headers={"Cache-Control": "no-store"},
                )
            response = await call_next(request)
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = "Authorization, X-LifeJacket-Organization, Origin"
            return response
        response = await call_next(request)
        if request.scope.get("path", "").startswith("/reporter/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response
