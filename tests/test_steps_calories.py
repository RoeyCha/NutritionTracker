from datetime import date, timedelta

from models import User
from steps_calories import estimate_steps_calories


def _user(weight_kg: float = 70.0) -> User:
    return User(
        username="steps_user",
        password_hash="hash",
        name="Steps User",
        birth_date=date.today() - timedelta(days=365 * 30),
        weight_kg=weight_kg,
    )


def test_steps_calories_scales_with_weight() -> None:
    estimate = estimate_steps_calories(_user(70.0), 7000, [])

    assert estimate.calories_burned == 280.0
    assert estimate.ai_estimated is False
    assert "7,000 steps" in estimate.explanation


def test_steps_calories_subtracts_walking_workout_overlap() -> None:
    workouts = [{"activity_type": "הליכה 4 ק\"מ, 50 דקות", "calories_burned": 200.0}]
    estimate = estimate_steps_calories(_user(70.0), 8000, workouts)

    assert estimate.calories_burned == 120.0
    assert "Subtracted 200" in estimate.explanation


def test_steps_calories_never_goes_negative() -> None:
    workouts = [{"activity_type": "Running 60 min", "calories_burned": 900.0}]
    estimate = estimate_steps_calories(_user(70.0), 2000, workouts)

    assert estimate.calories_burned == 0.0
