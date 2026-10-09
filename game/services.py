"""
Game rules, kept out of the views so they can be tested without HTTP.

Network calls to Google always happen *outside* database transactions, so the
database is never locked while we wait on the network.
"""
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Game, Round
from .scoring import haversine_m, score_for_distance
from .streetview import find_random_panorama, locate_panorama


class GameStateError(Exception):
    """The request doesn't fit the game's current state (HTTP 409)."""


@dataclass(frozen=True)
class GuessResult:
    round: Round
    answer_lat: float
    answer_lng: float


def start_game(*, finder=None):
    """Create a game and its first round."""
    panorama = (finder or find_random_panorama)()
    with transaction.atomic():
        game = Game.objects.create(total_rounds=settings.YG_ROUNDS_PER_GAME)
        Round.objects.create(game=game, number=1, pano_id=panorama.pano_id)
    return game


def start_next_round(game, *, finder=None):
    """Create the next round once the current one has been guessed."""
    last = game.rounds.order_by("-number").first()
    if game.is_finished or last is None or last.number >= game.total_rounds:
        raise GameStateError("This game has no rounds left.")
    if not last.is_guessed:
        raise GameStateError("Guess the current round before starting the next.")

    panorama = (finder or find_random_panorama)()
    try:
        with transaction.atomic():
            return Round.objects.create(game=game, number=last.number + 1, pano_id=panorama.pano_id)
    except IntegrityError:
        # Another request (e.g. a double click) created this round first.
        raise GameStateError("The next round has already started.")


def submit_guess(round_id, lat, lng, *, locator=None):
    """Score a guess, reveal the answer, and finish the game after the last round.

    Raises Round.DoesNotExist for an unknown round.
    """
    rnd = Round.objects.get(pk=round_id)
    if rnd.is_guessed:
        raise GameStateError("This round has already been guessed.")

    # Look up the true location first (network, no lock held).
    answer_lat, answer_lng = (locator or locate_panorama)(rnd.pano_id)

    with transaction.atomic():
        rnd = Round.objects.select_for_update().select_related("game").get(pk=round_id)
        if rnd.is_guessed:  # a concurrent request got here first
            raise GameStateError("This round has already been guessed.")

        now = timezone.now()
        rnd.guess_lat = lat
        rnd.guess_lng = lng
        rnd.distance_m = haversine_m(answer_lat, answer_lng, lat, lng)
        rnd.score = score_for_distance(rnd.distance_m)
        rnd.guessed_at = now
        rnd.save()

        if rnd.number >= rnd.game.total_rounds:
            rnd.game.finished_at = now
            rnd.game.save(update_fields=["finished_at"])
    return GuessResult(rnd, answer_lat, answer_lng)
