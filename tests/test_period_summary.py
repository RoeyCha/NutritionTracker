from datetime import date, timedelta

from fastapi.testclient import TestClient

from period_summary import build_period_summary, macros_goal_from_bmr, resolve_period


def test_macros_goal_from_bmr() -> None:
    goals = macros_goal_from_bmr(2000.0)
    assert goals is not None
    assert goals["protein_g"] == 125.0
    assert goals["carbohydrates_g"] == 225.0
    assert goals["fats_g"] == 66.7


def test_resolve_period_ranges() -> None:
    end = date(2026, 6, 29)
    start, resolved_end = resolve_period("7d", end, None)
    assert resolved_end == end
    assert (end - start).days == 6

    start_all, _ = resolve_period("all", end, date(2026, 1, 1))
    assert start_all == date(2026, 1, 1)


def test_period_summary_returns_requested_days(client: TestClient) -> None:
    end = date.today()
    response = client.get(
        f"/api/period-summary?range=7d&end_date={end.isoformat()}",
        headers=client.auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["range"] == "7d"
    assert len(payload["days"]) == 7
    assert payload["end_date"] == end.isoformat()
    assert "macro_goals" in payload
    assert "averages" in payload
    assert "calories_consumed" in payload["days"][0]


def test_period_summary_invalid_range(client: TestClient) -> None:
    response = client.get(
        f"/api/period-summary?range=2w&end_date={date.today().isoformat()}",
        headers=client.auth_headers,
    )
    assert response.status_code == 422


def test_period_summary_future_end_date_rejected(client: TestClient) -> None:
    future = (date.today() + timedelta(days=2)).isoformat()
    response = client.get(
        f"/api/period-summary?range=7d&end_date={future}",
        headers=client.auth_headers,
    )
    assert response.status_code == 422


def test_build_period_summary_includes_today_meal(client: TestClient) -> None:
    result = build_period_summary(client.db_session, client.test_user, "7d", date.today())
    assert any(day["calories_consumed"] > 0 for day in result["days"])


def test_calories_burned_includes_bmr_and_activity(client: TestClient) -> None:
    result = build_period_summary(client.db_session, client.test_user, "7d", date.today())
    today = result["days"][-1]
    bmr = float(client.test_user.bmr)
    assert today["calories_burned"] == bmr + today["activity_calories_burned"]
    assert today["activity_calories_burned"] >= 0