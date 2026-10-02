"""Pure geographic maths. No I/O, no dependencies, trivially testable.

Kept at the package root because both `context` (finding the nearest tide
station) and `dispatch` (ranking responders by distance) need it, and neither
should have to import from the other.
"""

from __future__ import annotations

import math

#: Mean radius of the Earth in kilometres (IUGG mean radius).
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres.

    Accurate to roughly 0.5% -- far better than we need, given that the inputs
    are a phone GPS fix and a rescue centre's street address.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_drive_minutes(distance_km: float, average_speed_kmh: float = 55.0) -> float:
    """Rough driving time from straight-line distance.

    A deliberate approximation, used only to order candidates and show the
    reporter an indicative wait. The responder app calls the Google Directions
    API for the real ETA once someone accepts.

    The 1.3 factor accounts for roads not being straight; coastal routes make
    this an underestimate, which is the safer direction for a reporter
    deciding whether to keep waiting.
    """
    road_distance = distance_km * 1.3
    return (road_distance / average_speed_kmh) * 60.0


def bounding_box(
    latitude: float, longitude: float, radius_km: float
) -> tuple[float, float, float, float]:
    """A (min_lat, max_lat, min_lon, max_lon) box enclosing the radius.

    Used to pre-filter database rows with a cheap SQL `BETWEEN` before paying
    for haversine on each one. The box is larger than the circle, so always
    filter again with `haversine_km` afterwards.
    """
    lat_delta = radius_km / 111.0  # one degree of latitude is ~111 km everywhere

    # Degrees of longitude shrink with latitude. Guard against the poles, where
    # cos() approaches zero and the division would explode.
    cos_lat = max(math.cos(math.radians(latitude)), 0.01)
    lon_delta = radius_km / (111.0 * cos_lat)

    return (
        latitude - lat_delta,
        latitude + lat_delta,
        longitude - lon_delta,
        longitude + lon_delta,
    )
