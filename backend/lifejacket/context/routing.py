"""Driving routes from a rescue centre to an incident.

The console draws these so a coordinator can see the actual road a team would
take, not the straight line between two dots -- on this coastline those differ
by a lot, because a bay or a headland sits between most pairs of points.

Uses OpenRouteService. The key lives on the server and the console asks *this*
API for routes, rather than calling OpenRouteService from the browser, so the
key is never in the web bundle.

Turn-by-turn navigation is deliberately not built here: the console deep-links
to Google Maps for that. This is for the overview map only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from lifejacket.config import settings
from lifejacket.geo import haversine_km

logger = logging.getLogger(__name__)


@dataclass
class Route:
    """A drivable route, or a straight-line fallback when routing is off."""

    #: [[longitude, latitude], ...] -- GeoJSON order, which is what MapLibre
    #: expects. Note it is the reverse of how coordinates are written
    #: everywhere else in this codebase.
    coordinates: list[list[float]] = field(default_factory=list)
    distance_km: float | None = None
    duration_minutes: float | None = None
    #: "openrouteservice" for a real road route, "straight_line" when no key
    #: is configured or the lookup failed. The console labels the difference,
    #: because a responder must not read a straight line as a drive time.
    source: str = "straight_line"


def driving_route(
    from_latitude: float,
    from_longitude: float,
    to_latitude: float,
    to_longitude: float,
) -> Route:
    """Road route between two points, falling back to a straight line.

    Never raises: a missing route must not stop a coordinator seeing the
    incident, so every failure degrades to the straight line that the rest of
    the system already uses for distance.
    """
    fallback = _straight_line(from_latitude, from_longitude, to_latitude, to_longitude)

    if not settings.ors_api_key:
        return fallback

    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.post(
                settings.ors_api_url,
                json={
                    # OpenRouteService takes [longitude, latitude].
                    "coordinates": [
                        [from_longitude, from_latitude],
                        [to_longitude, to_latitude],
                    ]
                },
                headers={
                    "Authorization": settings.ors_api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("OpenRouteService lookup failed: %s", exc)
        return fallback

    features = payload.get("features") or []
    if not features:
        logger.warning("OpenRouteService returned no route")
        return fallback

    feature = features[0]
    coordinates = (feature.get("geometry") or {}).get("coordinates") or []
    summary = (feature.get("properties") or {}).get("summary") or {}
    if not coordinates:
        return fallback

    return Route(
        coordinates=coordinates,
        distance_km=round(summary.get("distance", 0) / 1000, 1) or None,
        duration_minutes=round(summary.get("duration", 0) / 60) or None,
        source="openrouteservice",
    )


def _straight_line(
    from_latitude: float,
    from_longitude: float,
    to_latitude: float,
    to_longitude: float,
) -> Route:
    """Two points and the great-circle distance between them."""
    return Route(
        coordinates=[
            [from_longitude, from_latitude],
            [to_longitude, to_latitude],
        ],
        distance_km=round(
            haversine_km(from_latitude, from_longitude, to_latitude, to_longitude), 1
        ),
        duration_minutes=None,
        source="straight_line",
    )
