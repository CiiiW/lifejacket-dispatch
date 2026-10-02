"""Turning coordinates into place names and administrative areas.

This replaces the prototype's 50-entry hardcoded dictionary that mapped place
names like `"moss landing"` to counties like `["monterey"]`. That map only
worked for places someone had thought to add, and it was matched by substring
against a free-text location string.

Reverse geocoding gives us the county directly, from coordinates, anywhere.
That matters because the rescue-centre directory describes coverage by county
("Del Norte and Humboldt Counties, California"), so county is the join key
between where the animal is and who is allowed to respond.

Uses OpenStreetMap's Nominatim: free, keyless, and global. Note its usage
policy -- maximum one request per second, and a real contact in the
User-Agent. We cache aggressively to stay well inside that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from lifejacket.config import settings

logger = logging.getLogger(__name__)


@dataclass
class PlaceInfo:
    """A resolved location, split into the parts dispatch matching needs."""

    #: Short label for the UI, e.g. "Moss Landing, Monterey County, California".
    display_name: str = ""
    #: Most specific named feature: a beach, park, or neighbourhood.
    locality: str | None = None
    county: str | None = None
    state: str | None = None
    country: str | None = None
    #: Lower-cased terms used to match against a centre's `response_area`.
    #: Includes county, locality, and state so that a directory entry written
    #: as either "Monterey County" or "Moss Landing" will match.
    area_terms: list[str] = field(default_factory=list)


@lru_cache(maxsize=2048)
def reverse_geocode(latitude: float, longitude: float) -> PlaceInfo | None:
    """Resolve coordinates to a place. Returns None if the lookup fails.

    Cached on the exact coordinate pair. Callers should round to about four
    decimal places (roughly 11 m) before calling, so that two GPS fixes from
    the same beach share a cache entry.
    """
    params = {
        "lat": f"{latitude:.5f}",
        "lon": f"{longitude:.5f}",
        "format": "jsonv2",
        "zoom": "14",  # suburb/village level; finer returns house numbers
        "addressdetails": "1",
    }

    try:
        with httpx.Client(timeout=settings.http_timeout_seconds) as client:
            response = client.get(
                settings.nominatim_api_url,
                params=params,
                headers={"User-Agent": settings.http_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Reverse geocode failed for (%s, %s): %s", latitude, longitude, exc)
        return None

    if "error" in payload:
        logger.warning(
            "Nominatim error for (%s, %s): %s", latitude, longitude, payload["error"]
        )
        return None

    return _parse_place(payload)


def _parse_place(payload: dict) -> PlaceInfo:
    """Build a `PlaceInfo` from a Nominatim jsonv2 response.

    Nominatim's address keys vary by country and feature type, so each field
    tries several keys in decreasing specificity.
    """
    address = payload.get("address", {}) or {}

    locality = _first_of(
        address,
        "village",
        "town",
        "city",
        "hamlet",
        "suburb",
        "neighbourhood",
        "municipality",
    )
    county = _first_of(address, "county", "state_district")
    state = _first_of(address, "state", "province")
    country = address.get("country")

    # A named natural feature is the most useful thing to tell a responder --
    # "Drakes Beach" locates an animal better than "Inverness, Marin County".
    feature_name = payload.get("name") or None

    display_parts = [p for p in (feature_name or locality, county, state) if p]
    display_name = ", ".join(dict.fromkeys(display_parts))  # de-dupe, keep order

    # Normalise area terms: lower-cased, with the word "county" stripped, since
    # directory entries are inconsistent about including it.
    #
    # The state is deliberately NOT included. Every entry in the California
    # stranding directory contains the word "California", so matching on it
    # gave a centre 400 km away in Del Norte County the same area credit as the
    # one covering the incident's own county. County and locality are the
    # granularity at which coverage is actually assigned.
    area_terms: list[str] = []
    for value in (county, locality, feature_name):
        if not value:
            continue
        term = value.lower().replace(" county", "").strip()
        if term and term not in area_terms:
            area_terms.append(term)

    return PlaceInfo(
        display_name=display_name or payload.get("display_name", ""),
        locality=locality,
        county=county,
        state=state,
        country=country,
        area_terms=area_terms,
    )


def _first_of(mapping: dict, *keys: str) -> str | None:
    """Return the first present, non-empty value among `keys`."""
    for key in keys:
        value = mapping.get(key)
        if value:
            return str(value)
    return None
