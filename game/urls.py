from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/games", views.start_game, name="api-start-game"),
    path("api/games/<int:game_id>", views.game_summary, name="api-game-summary"),
    path("api/games/<int:game_id>/rounds", views.next_round, name="api-next-round"),
    path("api/rounds/<int:round_id>/guess", views.submit_guess, name="api-guess"),
]
