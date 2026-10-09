"""
One HTML page plus a small JSON API that the page calls with fetch():

    POST /api/games                      start a game, returns round 1
    POST /api/games/<id>/rounds          start the next round
    POST /api/rounds/<id>/guess          {"lat": .., "lng": ..} -> score + answer
    GET  /api/games/<id>                 summary for the results screen
"""
import json
import logging
import math
import os

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import Game, Round
from .scoring import MAX_ROUND_SCORE
from .streetview import StreetViewConfigError, StreetViewError

logger = logging.getLogger(__name__)


# --- serializers ---------------------------------------------------------------

def _round_public(rnd):
    """What the player may see while the round is open: no location."""
    return {
        "id": rnd.id,
        "number": rnd.number,
        "pano_id": rnd.pano_id,
        "guessed": rnd.is_guessed,
    }


def _round_scored(rnd):
    data = _round_public(rnd)
    data.update(
        guess={"lat": rnd.guess_lat, "lng": rnd.guess_lng},
        distance_m=round(rnd.distance_m, 1),
        score=rnd.score,
    )
    return data


def _game_state(game, rnd):
    return {
        "game_id": game.id,
        "total_rounds": game.total_rounds,
        "total_score": game.total_score,
        "round": _round_public(rnd),
    }


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _streetview_error(exc):
    if isinstance(exc, StreetViewConfigError):
        logger.error("Street View configuration problem: %s", exc)
    return _error(str(exc), 503)


# --- page --------------------------------------------------------------------

def _asset_version():
    """Newest modification time of our CSS/JS, appended as ?v= to their URLs so
    browsers fetch fresh copies after an edit instead of a cached old one."""
    paths = [finders.find("game/game.css"), finders.find("game/game.js")]
    return str(int(max((os.path.getmtime(p) for p in paths if p), default=0)))


@require_GET
@ensure_csrf_cookie
def index(request):
    return render(
        request,
        "game/index.html",
        {
            "asset_version": _asset_version(),
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
            "rounds_per_game": settings.YG_ROUNDS_PER_GAME,
            "max_round_score": f"{MAX_ROUND_SCORE:,}",
            # Handed to game.js through json_script (safely escaped).
            "client_config": {
                "googleMapsApiKey": settings.GOOGLE_MAPS_API_KEY,
                "googleMapsMapId": settings.GOOGLE_MAPS_MAP_ID,
                "roundsPerGame": settings.YG_ROUNDS_PER_GAME,
            },
        },
    )


# --- API -----------------------------------------------------------------------

@require_POST
def start_game(request):
    try:
        game = services.start_game()
    except StreetViewError as exc:
        return _streetview_error(exc)
    return JsonResponse(_game_state(game, game.rounds.get(number=1)), status=201)


@require_POST
def next_round(request, game_id):
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return _error("Game not found.", 404)
    try:
        rnd = services.start_next_round(game)
    except services.GameStateError as exc:
        return _error(str(exc), 409)
    except StreetViewError as exc:
        return _streetview_error(exc)
    return JsonResponse(_game_state(game, rnd), status=201)


def _parse_guess(request):
    """(lat, lng) from a JSON body, or raise ValueError with a message."""
    try:
        body = json.loads(request.body or b"{}")
        lat, lng = float(body["lat"]), float(body["lng"])
    except (ValueError, TypeError, KeyError):
        raise ValueError('Send JSON like {"lat": 40.44, "lng": -79.99}.')
    if not (math.isfinite(lat) and math.isfinite(lng)):
        raise ValueError("Coordinates must be finite numbers.")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Coordinates are out of range.")
    return lat, lng


@require_POST
def submit_guess(request, round_id):
    try:
        lat, lng = _parse_guess(request)
    except ValueError as exc:
        return _error(str(exc), 400)
    try:
        result = services.submit_guess(round_id, lat, lng)
    except Round.DoesNotExist:
        return _error("Round not found.", 404)
    except services.GameStateError as exc:
        return _error(str(exc), 409)
    except StreetViewError as exc:
        return _streetview_error(exc)
    rnd = result.round
    game = rnd.game
    revealed = _round_scored(rnd)
    # The answer is shown once, for the reveal map, and never stored.
    revealed["answer"] = {"lat": result.answer_lat, "lng": result.answer_lng}
    return JsonResponse(
        {
            "round": revealed,
            "total_score": game.total_score,
            "total_rounds": game.total_rounds,
            "game_over": game.is_finished,
        }
    )


@require_GET
def game_summary(request, game_id):
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return _error("Game not found.", 404)
    rounds = [
        _round_scored(r) if r.is_guessed else _round_public(r)
        for r in game.rounds.all()
    ]
    return JsonResponse(
        {
            "game_id": game.id,
            "total_rounds": game.total_rounds,
            "total_score": game.total_score,
            "max_score": game.total_rounds * MAX_ROUND_SCORE,
            "finished": game.is_finished,
            "rounds": rounds,
        }
    )
