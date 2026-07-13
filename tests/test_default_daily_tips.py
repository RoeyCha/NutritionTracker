import random

from bmr_calculator import apply_bmr_to_user
from default_daily_tips import (
    DEFAULT_TIP_COUNT,
    ONBOARDING_TIP_COUNT,
    RANDOM_TIP_SELECT_COUNT,
    _resolve_random_tip,
    build_default_daily_tips,
)
from fastapi.testclient import TestClient


def test_build_default_daily_tips_returns_twelve_items(client: TestClient) -> None:
    tips = build_default_daily_tips(client.test_user, "en", rng=random.Random(42))
    assert len(tips) == DEFAULT_TIP_COUNT
    assert tips[0]["category"] == "info"
    assert "Welcome to Nutrition Tracker" in tips[0]["text"]
    assert client.test_user.name in tips[0]["text"]


def test_onboarding_tips_are_fixed_random_pool_varies(client: TestClient) -> None:
    first = build_default_daily_tips(client.test_user, "en", rng=random.Random(1))
    second = build_default_daily_tips(client.test_user, "en", rng=random.Random(2))

    assert [tip["text"] for tip in first[:ONBOARDING_TIP_COUNT]] == [
        tip["text"] for tip in second[:ONBOARDING_TIP_COUNT]
    ]
    assert len({tip["text"] for tip in first[ONBOARDING_TIP_COUNT:]}) == RANDOM_TIP_SELECT_COUNT
    assert len({tip["text"] for tip in second[ONBOARDING_TIP_COUNT:]}) == RANDOM_TIP_SELECT_COUNT
    assert [tip["text"] for tip in first[ONBOARDING_TIP_COUNT:]] != [
        tip["text"] for tip in second[ONBOARDING_TIP_COUNT:]
    ]


def test_incomplete_profile_shows_completion_tip(client: TestClient) -> None:
    user = client.test_user
    user.birth_date = None
    user.weight_kg = None
    user.bmr = None
    client.db_session.flush()

    _, text = _resolve_random_tip(user, 11, "en")
    assert "Edit profile" in text
    _, he_text = _resolve_random_tip(user, 15, "he")
    assert "עריכת פרופיל" in he_text


def test_complete_profile_shows_bmr_in_random_pool(client: TestClient) -> None:
    user = client.test_user
    apply_bmr_to_user(user)
    client.db_session.flush()

    _, text = _resolve_random_tip(user, 11, "en")
    assert "BMR" in text
    assert f"{user.bmr:.0f}" in text


def test_hebrew_default_tips(client: TestClient) -> None:
    tips = build_default_daily_tips(client.test_user, "he", rng=random.Random(5))
    assert len(tips) == DEFAULT_TIP_COUNT
    assert "Nutrition Tracker" in tips[0]["text"]


def test_onboarding_section_has_six_tips(client: TestClient) -> None:
    tips = build_default_daily_tips(client.test_user, "en", rng=random.Random(0))
    onboarding = tips[:ONBOARDING_TIP_COUNT]
    assert len(onboarding) == 6
    assert all(tip["category"] == "info" for tip in onboarding)
    assert "Add Meal" in onboarding[1]["text"]
    assert "Add Workout" in onboarding[2]["text"]
    assert "calendar" in onboarding[5]["text"].lower()


def test_tip_20_protein_message_has_no_numeric_range(client: TestClient) -> None:
    user = client.test_user
    _, text = _resolve_random_tip(user, 20, "en")
    assert "protein" in text.lower()
    assert "g/kg" not in text
    assert "1.6" not in text
    assert "2.0" not in text

    _, he_text = _resolve_random_tip(user, 20, "he")
    assert "חלבון" in he_text
    assert "g/kg" not in he_text
