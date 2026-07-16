import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from daily_tip_feedback import fetch_feedback_for_prompt, toggle_tip_feedback
from gemini_daily_tips import (
    TIP_COUNT,
    MIN_TRACKING_DAYS,
    TRACKING_WINDOW_DAYS,
    _build_tips_prompt,
    _context_has_tracking_data,
    _default_daily_tips,
    _fallback_daily_tips,
    check_yesterday_prerequisites,
    fetch_three_day_context,
    get_or_create_daily_tips,
)
from models import DailySteps, DailyTipsCache, DailyWeight, Meal, Workout


@pytest.fixture(autouse=True)
def disable_gemini_for_daily_tips(monkeypatch: pytest.MonkeyPatch) -> None:
    import main as main_module

    monkeypatch.setattr(main_module, "GEMINI_API_KEY", None)
    monkeypatch.setattr("gemini_daily_tips.get_gemini_api_key", lambda: None)


def _yesterday() -> date:
    return date.today() - timedelta(days=1)


def seed_yesterday_prerequisites(
    db,
    user,
    *,
    steps_count: int = 8000,
    weight_kg: float = 75.0,
) -> None:
    yesterday = _yesterday()
    db.add(
        DailySteps(
            user_id=user.id,
            entry_date=yesterday,
            steps_count=steps_count,
            calories_burned=250.0,
        )
    )
    db.add(
        DailyWeight(
            user_id=user.id,
            entry_date=yesterday,
            weight_kg=weight_kg,
        )
    )
    db.commit()


def seed_meal_and_activity_data(db, user) -> None:
    """Seed meals/workouts on MIN_TRACKING_DAYS within the recent window."""
    for offset in range(MIN_TRACKING_DAYS):
        day = _yesterday() - timedelta(days=offset)
        logged_at = datetime.combine(day, datetime.min.time().replace(hour=12))
        db.add(
            Meal(
                user_id=user.id,
                food_name=f"Tracked oatmeal day {offset + 1}",
                calories=350.0,
                protein=12.0,
                carbohydrates=50.0,
                fats=8.0,
                logged_at=logged_at,
            )
        )
        db.add(
            Workout(
                user_id=user.id,
                activity_type=f"Tracked walk day {offset + 1}",
                calories_burned=200.0,
                logged_at=logged_at + timedelta(hours=2),
            )
        )
    db.commit()


def test_fetch_three_day_context_excludes_today(client: TestClient) -> None:
    context = fetch_three_day_context(client.db_session, client.test_user)
    assert len(context["days"]) == TRACKING_WINDOW_DAYS
    assert context["profile"]["name"] == client.test_user.name
    assert context["end_date"] == _yesterday().isoformat()
    today_iso = date.today().isoformat()
    assert all(day["date"] != today_iso for day in context["days"])


def test_check_yesterday_prerequisites_requires_steps_and_weight(client: TestClient) -> None:
    result = check_yesterday_prerequisites(client.db_session, client.test_user)
    assert result["prerequisites_met"] is False
    assert set(result["missing_prerequisites"]) == {"steps", "weight"}
    assert result["prerequisites_date"] == _yesterday().isoformat()

    seed_yesterday_prerequisites(client.db_session, client.test_user)
    ready = check_yesterday_prerequisites(client.db_session, client.test_user)
    assert ready["prerequisites_met"] is True
    assert ready["missing_prerequisites"] == []


def test_fallback_daily_tips_returns_twelve_items(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)
    context = fetch_three_day_context(client.db_session, client.test_user)
    tips = _fallback_daily_tips(context, "en")
    assert len(tips) == TIP_COUNT
    assert any(tip["category"] == "nutrition" for tip in tips)
    assert any(tip["category"] == "sport" for tip in tips)


def test_single_day_meal_activity_uses_hardcoded_tips(client: TestClient) -> None:
    day = _yesterday()
    logged_at = datetime.combine(day, datetime.min.time().replace(hour=12))
    client.db_session.add(
        Meal(
            user_id=client.test_user.id,
            food_name="Only yesterday meal",
            calories=400.0,
            logged_at=logged_at,
        )
    )
    client.db_session.commit()

    context = fetch_three_day_context(client.db_session, client.test_user)
    assert _context_has_tracking_data(context) is False

    result = get_or_create_daily_tips(
        client.test_user,
        client.db_session,
        language="en",
        force_refresh=True,
        api_key=None,
    )
    assert result["model"] == "general-no-data"
    assert result["personalized"] is False
    assert result["prerequisites_met"] is True


def test_two_of_five_days_still_uses_hardcoded_tips(client: TestClient) -> None:
    for offset in (0, 1):
        day = _yesterday() - timedelta(days=offset)
        logged_at = datetime.combine(day, datetime.min.time().replace(hour=12))
        client.db_session.add(
            Meal(
                user_id=client.test_user.id,
                food_name=f"Meal day {offset}",
                calories=300.0,
                logged_at=logged_at,
            )
        )
    client.db_session.commit()

    context = fetch_three_day_context(client.db_session, client.test_user)
    assert _context_has_tracking_data(context) is False

    result = get_or_create_daily_tips(
        client.test_user,
        client.db_session,
        language="en",
        api_key=None,
    )
    assert result["model"] == "general-no-data"
    assert result["personalized"] is False


def test_stale_personalized_cache_ignored_without_enough_tracking(client: TestClient) -> None:
    """Old personalized cache must not be served when meal/activity coverage is insufficient."""
    import json as json_lib

    client.db_session.add(
        DailyTipsCache(
            user_id=client.test_user.id,
            tip_date=date.today(),
            language="en",
            tips_json=json_lib.dumps(
                [{"category": "nutrition", "text": "Stale personalized tip that should not appear.", "preview": "Stale…"}]
            ),
            ai_estimated=True,
            model="gemini-2.5-flash",
        )
    )
    client.db_session.commit()

    result = get_or_create_daily_tips(
        client.test_user,
        client.db_session,
        language="en",
        api_key=None,
    )
    assert result["model"] == "general-no-data"
    assert result["personalized"] is False
    assert result["cached"] is False
    assert "Stale personalized tip" not in result["tips"][0]["text"]
    assert (
        client.db_session.query(DailyTipsCache)
        .filter(
            DailyTipsCache.user_id == client.test_user.id,
            DailyTipsCache.tip_date == date.today(),
            DailyTipsCache.language == "en",
        )
        .first()
        is None
    )


def test_default_daily_tips_when_no_meal_or_activity_data(client: TestClient) -> None:
    # Even without yesterday steps/weight, missing meals/workouts → hardcoded tips, no block.
    context = fetch_three_day_context(client.db_session, client.test_user)
    assert _context_has_tracking_data(context) is False

    tips = _default_daily_tips(client.test_user, "en")
    assert len(tips) == TIP_COUNT
    assert tips[0]["category"] == "info"

    result = get_or_create_daily_tips(
        client.test_user,
        client.db_session,
        language="en",
        force_refresh=True,
        api_key=None,
    )
    assert result["prerequisites_met"] is True
    assert result["personalized"] is False
    assert result["model"] == "general-no-data"
    assert result["tips"][0]["category"] == "info"
    assert len(result["tips"]) == TIP_COUNT


def test_get_or_create_blocked_when_meals_exist_but_steps_weight_missing(client: TestClient) -> None:
    seed_meal_and_activity_data(client.db_session, client.test_user)

    result = get_or_create_daily_tips(
        client.test_user,
        client.db_session,
        language="en",
        force_refresh=True,
        api_key=None,
    )
    assert result["prerequisites_met"] is False
    assert result["model"] == "prerequisites-unmet"
    assert result["tips"] == []
    assert set(result["missing_prerequisites"]) == {"steps", "weight"}


def test_get_daily_tips_caches_for_day(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)

    first = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert first.status_code == 200
    body = first.json()
    assert body["prerequisites_met"] is True
    assert body["personalized"] is True
    assert len(body["tips"]) == TIP_COUNT
    assert body["language"] == "en"
    assert "preview" in body["tips"][0]
    assert body["cached"] is False

    second = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["cached"] is True
    assert second_body["tips"][0]["text"] == body["tips"][0]["text"]
    assert second_body["tips"][1]["text"] == body["tips"][1]["text"]


def test_refresh_daily_tips_blocked_without_prerequisites(client: TestClient) -> None:
    seed_meal_and_activity_data(client.db_session, client.test_user)

    refreshed = client.post(
        "/api/daily-tips/refresh",
        headers=client.auth_headers,
        json={"language": "en"},
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["prerequisites_met"] is False
    assert payload["model"] == "prerequisites-unmet"
    assert payload["tips"] == []
    assert payload["cached"] is False


def test_refresh_without_meal_activity_returns_hardcoded_tips(client: TestClient) -> None:
    refreshed = client.post(
        "/api/daily-tips/refresh",
        headers=client.auth_headers,
        json={"language": "en"},
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["prerequisites_met"] is True
    assert payload["model"] == "general-no-data"
    assert payload["personalized"] is False
    assert payload["tips"][0]["category"] == "info"
    assert len(payload["tips"]) == TIP_COUNT


def test_refresh_daily_tips_generates_when_prerequisites_met(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)

    refreshed = client.post(
        "/api/daily-tips/refresh",
        headers=client.auth_headers,
        json={"language": "en"},
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["prerequisites_met"] is True
    assert payload["personalized"] is True
    assert len(payload["tips"]) == TIP_COUNT
    assert payload["model"] == "local-fallback"

    cached = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert cached.status_code == 200
    cached_body = cached.json()
    assert cached_body["cached"] is True
    assert cached_body["tips"][0]["text"] == payload["tips"][0]["text"]


def test_refresh_daily_tips_replaces_cache(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)
    client.get("/api/daily-tips?language=en", headers=client.auth_headers).json()
    refreshed = client.post(
        "/api/daily-tips/refresh",
        headers=client.auth_headers,
        json={"language": "en"},
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["cached"] is False
    assert payload["prerequisites_met"] is True
    assert payload["personalized"] is True
    assert len(payload["tips"]) == TIP_COUNT


def test_daily_tips_separate_cache_per_language(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)
    english = client.get("/api/daily-tips?language=en", headers=client.auth_headers).json()
    hebrew = client.get("/api/daily-tips?language=he", headers=client.auth_headers).json()

    assert english["language"] == "en"
    assert hebrew["language"] == "he"
    assert english["prerequisites_met"] is True
    assert hebrew["prerequisites_met"] is True
    assert english["personalized"] is True
    assert hebrew["personalized"] is True

    cached_count = (
        client.db_session.query(DailyTipsCache)
        .filter(DailyTipsCache.user_id == client.test_user.id)
        .count()
    )
    assert cached_count == 2


def test_get_or_create_daily_tips_persists_json(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)

    result = get_or_create_daily_tips(client.test_user, client.db_session, language="en", api_key=None)
    client.db_session.commit()

    record = (
        client.db_session.query(DailyTipsCache)
        .filter(DailyTipsCache.user_id == client.test_user.id, DailyTipsCache.tip_date == date.today())
        .first()
    )
    assert record is not None
    stored = json.loads(record.tips_json)
    assert len(stored) == TIP_COUNT
    assert result["tips"][0]["text"] == stored[0]["text"]


def test_api_returns_hardcoded_tips_without_meal_activity(client: TestClient) -> None:
    response = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["prerequisites_met"] is True
    assert body["personalized"] is False
    assert body["model"] == "general-no-data"
    assert body["tips"][0]["category"] == "info"
    assert len(body["tips"]) == TIP_COUNT


def test_api_blocks_when_meals_exist_but_steps_weight_missing(client: TestClient) -> None:
    seed_meal_and_activity_data(client.db_session, client.test_user)

    response = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["prerequisites_met"] is False
    assert body["model"] == "prerequisites-unmet"
    assert body["tips"] == []
    assert set(body["missing_prerequisites"]) == {"steps", "weight"}


def test_daily_tips_include_feedback_field(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    seed_meal_and_activity_data(client.db_session, client.test_user)
    response = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert response.status_code == 200
    assert "feedback" in response.json()["tips"][0]


def test_tip_feedback_toggle(client: TestClient) -> None:
    tip_text = "On Monday you logged oatmeal — add protein at lunch tomorrow."
    payload = {
        "tip_text": tip_text,
        "category": "nutrition",
        "language": "en",
        "action": "like",
    }

    liked = client.post("/api/daily-tips/feedback", headers=client.auth_headers, json=payload)
    assert liked.status_code == 200
    assert liked.json()["rating"] == "like"

    cleared = client.post("/api/daily-tips/feedback", headers=client.auth_headers, json=payload)
    assert cleared.status_code == 200
    assert cleared.json()["rating"] is None

    disliked = client.post(
        "/api/daily-tips/feedback",
        headers=client.auth_headers,
        json={**payload, "action": "dislike"},
    )
    assert disliked.status_code == 200
    assert disliked.json()["rating"] == "dislike"


def test_build_tips_prompt_includes_user_feedback(client: TestClient) -> None:
    seed_yesterday_prerequisites(client.db_session, client.test_user)
    tip_text = "Your steps dropped on Tuesday — schedule a 25-minute walk."
    toggle_tip_feedback(
        client.db_session,
        client.test_user,
        tip_text,
        "sport",
        "en",
        "like",
    )
    client.db_session.commit()

    context = fetch_three_day_context(client.db_session, client.test_user)
    feedback = fetch_feedback_for_prompt(client.db_session, client.test_user.id, "en")
    prompt = _build_tips_prompt(client.test_user, context, "en", feedback)

    assert tip_text in prompt
    assert "LIKED" in prompt
