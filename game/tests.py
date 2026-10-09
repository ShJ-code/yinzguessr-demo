"""
Tests run without network access: Google Street View is replaced by fakes.

    python manage.py test
"""
import json
import random
from unittest import mock

import requests
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import streetview
from .models import Game, Round
from .scoring import haversine_m, score_for_distance
from .streetview import (
    PITTSBURGH_BBOX,
    NoPanoramaFound,
    Panorama,
    StreetViewConfigError,
    StreetViewError,
)

# The Cathedral of Learning, used as the true spot in API tests.
CATHEDRAL = Panorama(pano_id="pano-cathedral", lat=40.4443, lng=-79.9532)


def metadata(status="OK", pano_id="abc", lat=40.44, lng=-79.99, copyright="© Google"):
    data = {"status": status}
    if status == "OK":
        data.update(pano_id=pano_id, location={"lat": lat, "lng": lng}, copyright=copyright, date="2023-06")
    return data


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._payload


class FakeSession:
    """Returns queued responses (or raises queued exceptions) in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- scoring -------------------------------------------------------------------

class ScoringTests(TestCase):
    def test_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_m(0, 0, 1, 0), 111_195, delta=1)

    def test_same_point_is_zero(self):
        self.assertEqual(haversine_m(40.44, -79.99, 40.44, -79.99), 0)

    def test_cathedral_to_point_state_park(self):
        # About 5 km from Oakland to the Point.
        d = haversine_m(40.4443, -79.9532, 40.4416, -80.0124)
        self.assertAlmostEqual(d, 5_010, delta=60)

    def test_score_curve(self):
        self.assertEqual(score_for_distance(0), 5000)
        self.assertEqual(score_for_distance(1000), 3352)  # 5000 * e^-0.4
        self.assertEqual(score_for_distance(2500), 1839)  # 5000 / e
        self.assertEqual(score_for_distance(5000), 677)
        self.assertEqual(score_for_distance(50_000), 0)

    def test_negative_distance_rejected(self):
        with self.assertRaises(ValueError):
            score_for_distance(-1)


# --- picking and locating panoramas ---------------------------------------------

@override_settings(GOOGLE_MAPS_API_KEY="test-key")
class StreetViewTests(TestCase):
    def test_random_point_inside_city_bbox(self):
        rng = random.Random(7)
        min_lng, min_lat, max_lng, max_lat = PITTSBURGH_BBOX
        for _ in range(500):
            lat, lng = streetview.random_point(rng)
            self.assertTrue(min_lat <= lat <= max_lat and min_lng <= lng <= max_lng)

    def test_finds_google_panorama_and_sends_search_params(self):
        session = FakeSession(FakeResponse(metadata(pano_id="p1", lat=40.45, lng=-79.95)))
        found = streetview.find_random_panorama(random.Random(1), session=session)
        self.assertEqual(found, Panorama("p1", 40.45, -79.95))
        params = session.calls[0]
        self.assertEqual(params["source"], "outdoor")
        self.assertEqual(params["radius"], streetview.SEARCH_RADIUS_M)
        self.assertEqual(params["key"], "test-key")

    def test_retries_empty_spots_errors_and_user_photos(self):
        session = FakeSession(
            FakeResponse(metadata(status="ZERO_RESULTS")),
            requests.Timeout("slow"),
            FakeResponse(metadata(pano_id="user", copyright="© Some Person")),
            FakeResponse(metadata(pano_id="google")),
        )
        found = streetview.find_random_panorama(random.Random(3), session=session)
        self.assertEqual(found.pano_id, "google")
        self.assertEqual(len(session.calls), 4)

    def test_gives_up_after_max_attempts(self):
        session = FakeSession(*[FakeResponse(metadata(status="ZERO_RESULTS")) for _ in range(4)])
        with self.assertRaises(NoPanoramaFound):
            streetview.find_random_panorama(random.Random(3), session=session, max_attempts=4)

    def test_rejected_key_stops_immediately(self):
        session = FakeSession(
            FakeResponse({"status": "REQUEST_DENIED", "error_message": "The provided API key is invalid."}),
            FakeResponse(metadata()),
        )
        with self.assertRaisesRegex(StreetViewConfigError, "invalid"):
            streetview.find_random_panorama(random.Random(3), session=session)
        self.assertEqual(len(session.calls), 1)

    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_missing_key(self):
        with self.assertRaises(StreetViewConfigError):
            streetview.find_random_panorama(random.Random(3), session=FakeSession())

    def test_locate_panorama(self):
        session = FakeSession(FakeResponse(metadata(pano_id="p1", lat=40.1, lng=-79.9)))
        self.assertEqual(streetview.locate_panorama("p1", session=session), (40.1, -79.9))
        self.assertEqual(session.calls[0]["pano"], "p1")

    def test_locate_missing_panorama(self):
        session = FakeSession(FakeResponse({"status": "NOT_FOUND"}))
        with self.assertRaises(StreetViewError):
            streetview.locate_panorama("gone", session=session)

    def test_locate_network_failure(self):
        session = FakeSession(requests.ConnectionError("offline"))
        with self.assertRaises(StreetViewError):
            streetview.locate_panorama("p1", session=session)


# --- JSON API --------------------------------------------------------------------

@override_settings(GOOGLE_MAPS_API_KEY="test-key", YG_ROUNDS_PER_GAME=3)
@mock.patch("game.services.locate_panorama", return_value=(CATHEDRAL.lat, CATHEDRAL.lng))
@mock.patch("game.services.find_random_panorama", return_value=CATHEDRAL)
class ApiTests(TestCase):
    def post(self, url, body=None):
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json")

    def start(self):
        response = self.post(reverse("api-start-game"))
        self.assertEqual(response.status_code, 201)
        return response.json()

    def guess(self, round_id, lat=CATHEDRAL.lat, lng=CATHEDRAL.lng):
        return self.post(reverse("api-guess", args=[round_id]), {"lat": lat, "lng": lng})

    def test_index_page(self, _finder, _locator):
        response = self.client.get(reverse("index"))
        self.assertContains(response, "Start game")
        self.assertIn("csrftoken", response.cookies)
        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")

    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_index_page_without_key_explains_setup(self, _finder, _locator):
        response = self.client.get(reverse("index"))
        self.assertContains(response, "Google Maps API key missing")
        self.assertNotContains(response, 'id="start-btn"')

    def test_open_round_hides_the_location(self, _finder, _locator):
        data = self.start()
        self.assertEqual(data["round"]["number"], 1)
        self.assertEqual(data["round"]["pano_id"], CATHEDRAL.pano_id)
        self.assertNotIn("lat", json.dumps(data))

    def test_perfect_guess_scores_5000_and_reveals_once(self, _finder, locator):
        round_id = self.start()["round"]["id"]
        body = self.guess(round_id).json()
        self.assertEqual(body["round"]["score"], 5000)
        self.assertEqual(body["round"]["answer"], {"lat": CATHEDRAL.lat, "lng": CATHEDRAL.lng})
        self.assertEqual(body["total_score"], 5000)
        self.assertFalse(body["game_over"])
        locator.assert_called_once_with(CATHEDRAL.pano_id)
        # The location is not stored, so later reads can't return it.
        self.assertFalse(any(f.name in ("lat", "lng") for f in Round._meta.get_fields()))

    def test_full_game_of_three_rounds(self, finder, _locator):
        data = self.start()
        game_id = data["game_id"]
        for number in (1, 2, 3):
            self.assertEqual(data["round"]["number"], number)
            body = self.guess(data["round"]["id"], lat=40.4416, lng=-80.0124).json()
            self.assertEqual(body["game_over"], number == 3)
            if number < 3:
                data = self.post(reverse("api-next-round", args=[game_id])).json()

        self.assertEqual(finder.call_count, 3)
        summary = self.client.get(reverse("api-game-summary", args=[game_id])).json()
        self.assertTrue(summary["finished"])
        self.assertEqual(summary["max_score"], 15000)
        self.assertEqual(len(summary["rounds"]), 3)
        self.assertEqual(summary["total_score"], sum(r["score"] for r in summary["rounds"]))
        self.assertNotIn("answer", json.dumps(summary))
        self.assertIsNotNone(Game.objects.get(pk=game_id).finished_at)
        self.assertEqual(self.post(reverse("api-next-round", args=[game_id])).status_code, 409)

    def test_next_round_requires_a_guess_first(self, _finder, _locator):
        data = self.start()
        response = self.post(reverse("api-next-round", args=[data["game_id"]]))
        self.assertEqual(response.status_code, 409)

    def test_round_can_only_be_guessed_once(self, _finder, _locator):
        round_id = self.start()["round"]["id"]
        self.assertEqual(self.guess(round_id).status_code, 200)
        self.assertEqual(self.guess(round_id, lat=40.0, lng=-80.0).status_code, 409)
        self.assertEqual(Round.objects.get(pk=round_id).score, 5000)

    def test_bad_guesses_are_rejected(self, _finder, _locator):
        round_id = self.start()["round"]["id"]
        url = reverse("api-guess", args=[round_id])
        self.assertEqual(self.post(url, {"lat": "north"}).status_code, 400)
        self.assertEqual(self.post(url, {"lat": 95, "lng": 0}).status_code, 400)
        self.assertEqual(self.client.post(url, data="not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.post(url, {"lat": "nan", "lng": 0}).status_code, 400)
        self.assertFalse(Round.objects.get(pk=round_id).is_guessed)

    def test_unknown_ids(self, _finder, _locator):
        self.assertEqual(self.guess(999).status_code, 404)
        self.assertEqual(self.post(reverse("api-next-round", args=[999])).status_code, 404)
        self.assertEqual(self.client.get(reverse("api-game-summary", args=[999])).status_code, 404)

    def test_wrong_methods(self, _finder, _locator):
        self.assertEqual(self.client.get(reverse("api-start-game")).status_code, 405)
        self.assertEqual(self.client.post(reverse("api-game-summary", args=[1])).status_code, 405)

    def test_no_panorama_returns_503_and_saves_nothing(self, finder, _locator):
        finder.side_effect = NoPanoramaFound("No Street View panorama found after 15 random spots.")
        response = self.post(reverse("api-start-game"))
        self.assertEqual(response.status_code, 503)
        self.assertIn("No Street View panorama", response.json()["error"])
        self.assertEqual(Game.objects.count(), 0)

    def test_scoring_lookup_failure_leaves_round_open(self, _finder, locator):
        round_id = self.start()["round"]["id"]
        locator.side_effect = StreetViewError("Couldn't reach Google to score this guess.")
        self.assertEqual(self.guess(round_id).status_code, 503)
        self.assertFalse(Round.objects.get(pk=round_id).is_guessed)
        locator.side_effect = None
        self.assertEqual(self.guess(round_id).status_code, 200)

    def test_csrf_is_enforced(self, _finder, _locator):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("api-start-game")).status_code, 403)
        client.get(reverse("index"))  # sets the csrftoken cookie
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("api-start-game"), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
