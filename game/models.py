from django.db import models
from django.db.models import Sum


class Game(models.Model):
    """One single-player game of `total_rounds` rounds."""

    created_at = models.DateTimeField(auto_now_add=True)
    total_rounds = models.PositiveSmallIntegerField()
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Game {self.pk}"

    @property
    def is_finished(self):
        return self.finished_at is not None

    @property
    def total_score(self):
        return self.rounds.aggregate(total=Sum("score"))["total"] or 0


class Round(models.Model):
    """One Street View panorama to guess.

    Only the panorama ID is stored: Google's terms allow caching panorama IDs
    but not Street View coordinates, so the true location is looked up again
    when the player guesses and is never saved.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="rounds")
    number = models.PositiveSmallIntegerField()  # 1-based
    created_at = models.DateTimeField(auto_now_add=True)

    pano_id = models.CharField(max_length=128)

    # Filled in when the player guesses (the player's own data).
    guess_lat = models.FloatField(null=True, blank=True)
    guess_lng = models.FloatField(null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    score = models.PositiveIntegerField(null=True, blank=True)
    guessed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["game", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "number"], name="unique_round_number_per_game"
            ),
        ]

    def __str__(self):
        return f"Game {self.game_id}, round {self.number}"

    @property
    def is_guessed(self):
        return self.guessed_at is not None
