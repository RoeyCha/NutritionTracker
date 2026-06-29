import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from gemini_daily_tips import (
    TIP_COUNT,
    _context_has_tracking_data,
    _fallback_daily_tips,
    _general_daily_tips,
    fetch_three_day_context,
    get_or_create_daily_tips,
)
from models import DailyTipsCache


def test_fetch_three_day_context_excludes_today(client: TestClient) -> None:
    context = fetch_three_day_context(client.db_session, client.test_user)
    assert len(context["days"]) == 3
    assert context["profile"]["name"] == client.test_user.name
    assert context["end_date"] == (date.today() - timedelta(days=1)).isoformat()
    today_iso = date.today().isoformat()
    assert all(day["date"] != today_iso for day in context["days"])


def test_fallback_daily_tips_returns_twelve_items(client: TestClient) -> None:
    context = fetch_three_day_context(client.db_session, client.test_user)
    tips = _fallback_daily_tips(context, "en")
    assert len(tips) == TIP_COUNT
    assert any(tip["category"] == "nutrition" for tip in tips)
    assert any(tip["category"] == "sport" for tip in tips)


def test_general_daily_tips_when_no_tracking_data(client: TestClient) -> None:
    context = fetch_three_day_context(client.db_session, client.test_user)
    assert _context_has_tracking_data(context) is False

    tips = _general_daily_tips("en")
    assert len(tips) == TIP_COUNT
    assert tips[0]["category"] == "info"
    assert "personalized" in tips[0]["text"].lower()

    result = get_or_create_daily_tips(
        client.test_user,
        client.db_session,
        language="en",
        force_refresh=True,
        api_key=None,
    )
    assert result["personalized"] is False
    assert result["model"] == "general-no-data"
    assert result["tips"][0]["category"] == "info"


def test_get_daily_tips_caches_for_day(client: TestClient) -> None:
    first = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert first.status_code == 200
    body = first.json()
    assert len(body["tips"]) == TIP_COUNT
    assert body["language"] == "en"
    assert "preview" in body["tips"][0]

    second = client.get("/api/daily-tips?language=en", headers=client.auth_headers)
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["tips"] == body["tips"]


def test_refresh_daily_tips_without_data_shows_general(client: TestClient) -> None:
    refreshed = client.post(
        "/api/daily-tips/refresh",
        headers=client.auth_headers,
        json={"language": "en"},
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["personalized"] is False
    assert payload["tips"][0]["category"] == "info"
    assert len(payload["tips"]) == TIP_COUNT


def test_refresh_daily_tips_replaces_cache(client: TestClient) -> None:
    first = client.get("/api/daily-tips?language=en", headers=client.auth_headers).json()
    refreshed = client.post(
        "/api/daily-tips/refresh",
        headers=client.auth_headers,
        json={"language": "en"},
    )
    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["cached"] is False
    assert len(payload["tips"]) == TIP_COUNT


def test_daily_tips_separate_cache_per_language(client: TestClient) -> None:
    english = client.get("/api/daily-tips?language=en", headers=client.auth_headers).json()
    hebrew = client.get("/api/daily-tips?language=he", headers=client.auth_headers).json()

    assert english["language"] == "en"
    assert hebrew["language"] == "he"

    cached_en = (
        client.db_session.query(DailyTipsCache)
        .filter(DailyTipsCache.user_id == client.test_user.id, DailyTipsCache.language == "en")
        .count()
    )
    cached_he = (
        client.db_session.query(DailyTipsCache)
        .filter(DailyTipsCache.user_id == client.test_user.id, DailyTipsCache.language == "he")
        .count()
    )
    assert cached_en == 1
    assert cached_he == 1


def test_get_or_create_daily_tips_persists_json(client: TestClient) -> None:
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
