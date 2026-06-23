from datetime import date, timedelta

from bmr_calculator import (
    calculate_bmr_mifflin_st_jeor,
    calculate_user_bmr,
    typical_height_cm,
)
from models import User


def test_typical_height_cm_by_gender() -> None:
    assert typical_height_cm("male") == 175.0
    assert typical_height_cm("female") == 162.0
    assert typical_height_cm(None) == 170.0


def test_calculate_bmr_mifflin_st_jeor_male() -> None:
    # 75 kg, 30 years, 175 cm -> 10*75 + 6.25*175 - 5*30 + 5 = 1698.8
    assert calculate_bmr_mifflin_st_jeor(75, 30, gender="male", height_cm=175) == 1698.8


def test_calculate_bmr_mifflin_st_jeor_female() -> None:
    # 68 kg, 28 years, 162 cm -> 10*68 + 6.25*162 - 5*28 - 161 = 1391.5
    assert calculate_bmr_mifflin_st_jeor(68, 28, gender="female", height_cm=162) == 1391.5


def test_calculate_user_bmr_requires_profile_fields() -> None:
    incomplete = User(
        username="u",
        password_hash="x",
        name="User",
        birth_date=date.today() - timedelta(days=365 * 30),
        weight_kg=None,
    )
    assert calculate_user_bmr(incomplete) is None


def test_calculate_user_bmr_uses_profile_height() -> None:
    user = User(
        username="u",
        password_hash="x",
        name="User",
        gender="male",
        birth_date=date(1996, 1, 1),
        height_cm=180.0,
        weight_kg=75.0,
    )
    estimate = calculate_user_bmr(user)
    assert estimate is not None
    assert estimate.ai_estimated is False
    assert "180 cm" in estimate.explanation
    assert "typical estimate" not in estimate.explanation
    assert "kcal/day" in estimate.explanation


def test_calculate_user_bmr_is_local_only() -> None:
    birth_date = date(1996, 1, 1)
    user = User(
        username="u",
        password_hash="x",
        name="User",
        gender="male",
        birth_date=birth_date,
        height_cm=175.0,
        weight_kg=75.0,
    )
    estimate = calculate_user_bmr(user)
    assert estimate is not None
    from profile_utils import age_years_from_birth_date

    age = age_years_from_birth_date(birth_date)
    assert estimate.bmr == calculate_bmr_mifflin_st_jeor(75, age, gender="male", height_cm=175)
    assert estimate.ai_estimated is False
    assert "Mifflin-St Jeor" in estimate.explanation
