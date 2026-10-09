"""
Pick a random Google Street View panorama in Pittsburgh, and look up where a
panorama is, using the Street View Static API *metadata* endpoint. Metadata
requests are free and don't count against the Street View quotas:
https://developers.google.com/maps/documentation/streetview/metadata

Google Maps Platform terms let us keep panorama IDs but not Street View
coordinates, so a round stores only the panorama ID. The location is looked up
again (free) when the player guesses.
"""
import logging
import random
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"

# Rectangle around the City of Pittsburgh: (min_lng, min_lat, max_lng, max_lat).
# A few panoramas will be just outside city limits (e.g. Millvale, Dormont).
PITTSBURGH_BBOX = (-80.0955, 40.3613, -79.8657, 40.5012)

# How far from the random point Google may look for a panorama, in metres.
SEARCH_RADIUS_M = 300
MAX_ATTEMPTS = 15
REQUEST_TIMEOUT_S = 10


class StreetViewError(Exception):
    """Base class for anything that stops us from producing or scoring a round."""


class StreetViewConfigError(StreetViewError):
    """The API key is missing or Google rejected it."""


class NoPanoramaFound(StreetViewError):
    """Every attempt came back without a usable panorama."""


@dataclass(frozen=True)
class Panorama:
    pano_id: str
    lat: float
    lng: float


def _api_key():
    key = settings.GOOGLE_MAPS_API_KEY
    if not key:
        raise StreetViewConfigError(
            "GOOGLE_MAPS_API_KEY is not set. Add it to .env (see README.md)."
        )
    return key


def fetch_metadata(params, *, session=requests):
    """Call the metadata endpoint and return its JSON, or raise.

    Statuses: OK, ZERO_RESULTS, NOT_FOUND (no panorama) are returned to the
    caller; REQUEST_DENIED and friends become StreetViewConfigError.
    """
    response = session.get(
        METADATA_URL,
        params={**params, "key": _api_key()},
        timeout=REQUEST_TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()
    status = data.get("status")
    if status in ("REQUEST_DENIED", "OVER_QUERY_LIMIT", "INVALID_REQUEST"):
        detail = data.get("error_message") or (
            "check GOOGLE_MAPS_API_KEY and that the Street View Static API is enabled for it"
        )
        raise StreetViewConfigError(f"Google Street View answered {status}: {detail}")
    return data


def _panorama_from(data):
    """A Panorama from a metadata response, or None if it isn't usable.

    Only Google's own imagery counts: user-contributed photo spheres are often
    indoors, low quality, or labelled with the place name.
    """
    if data.get("status") != "OK":
        return None
    if "Google" not in (data.get("copyright") or ""):
        return None
    location = data.get("location") or {}
    if not data.get("pano_id") or "lat" not in location or "lng" not in location:
        return None
    return Panorama(str(data["pano_id"]), float(location["lat"]), float(location["lng"]))


def random_point(rng, bbox=PITTSBURGH_BBOX):
    min_lng, min_lat, max_lng, max_lat = bbox
    return rng.uniform(min_lat, max_lat), rng.uniform(min_lng, max_lng)


def find_random_panorama(rng=None, *, session=requests, max_attempts=MAX_ATTEMPTS):
    """Try random spots until Google has an outdoor panorama near one."""
    _api_key()
    rng = rng or random.SystemRandom()

    for attempt in range(1, max_attempts + 1):
        lat, lng = random_point(rng)
        try:
            data = fetch_metadata(
                {
                    "location": f"{lat:.6f},{lng:.6f}",
                    "radius": SEARCH_RADIUS_M,
                    "source": "outdoor",
                },
                session=session,
            )
        except StreetViewConfigError:
            raise
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Street View lookup failed (attempt %d): %s", attempt, exc)
            continue
        panorama = _panorama_from(data)
        if panorama:
            logger.info("Round panorama %s found on attempt %d", panorama.pano_id, attempt)
            return panorama
        logger.info(
            "No usable panorama near %.5f,%.5f (attempt %d, status %s)",
            lat, lng, attempt, data.get("status"),
        )

    raise NoPanoramaFound(
        f"No Street View panorama found after {max_attempts} random spots. Try again."
    )


def locate_panorama(pano_id, *, session=requests):
    """(lat, lng) of a panorama, looked up fresh for scoring."""
    try:
        data = fetch_metadata({"pano": pano_id}, session=session)
    except StreetViewConfigError:
        raise
    except (requests.RequestException, ValueError) as exc:
        raise StreetViewError(f"Couldn't reach Google to score this guess ({exc}). Try again.")
    location = data.get("location") or {}
    if data.get("status") != "OK" or "lat" not in location:
        raise StreetViewError(
            "Google no longer has this panorama, so the round can't be scored."
        )
    return float(location["lat"]), float(location["lng"])
