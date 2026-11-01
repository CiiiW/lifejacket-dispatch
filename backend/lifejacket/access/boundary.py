"""Network mode exposes only reviewed endpoints; legacy routes fail closed."""

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
        return await call_next(request)
