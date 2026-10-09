"""Distance and points for one guess."""
import math

EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius
MAX_ROUND_SCORE = 5000
# Points fall off exponentially with distance: 1 km away keeps ~67%,
# 2.5 km keeps ~37%, 5 km keeps ~14%.
SCORE_SCALE_M = 2500.0


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance between two lat/lng points, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def score_for_distance(distance_m):
    """round(5000 * e^(-d / 2500 m)); 5000 for a perfect guess."""
    if distance_m < 0:
        raise ValueError("distance must be non-negative")
    return round(MAX_ROUND_SCORE * math.exp(-distance_m / SCORE_SCALE_M))
