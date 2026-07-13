from datetime import date, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_calories import CalorieEstimate
from steps_calories import StepsCalorieEstimate


def test_home_page_loads(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Nutrition Tracker" in response.text
    assert "Weekly Status" in response.text
    assert 'name="description"' in response.text
    assert 'property="og:title"' in response.text
    assert 'property="og:description"' in response.text
    assert 'property="og:url"' in response.text
    assert "<main" in response.text
    assert "<footer" in response.text


def test_capabilities_endpoint_lists_features(empty_client: TestClient) -> None:
    response = empty_client.get("/api/capabilities")

    assert response.status_code == 200
    caps = response.json()["capabilities"]
    assert caps["meal_edit"] is True
    assert caps["meal_delete"] is True
    assert caps["workout_edit"] is True
    assert caps["workout_delete"] is True
    assert caps["weight"] is True
    assert caps["data_export"] is True
    assert caps["data_import"] is True


def test_summary_requires_auth(empty_client: TestClient) -> None:
    response = empty_client.get(f"/api/summary?date={date.today().isoformat()}")

    assert response.status_code == 401


def test_nutrition_summary_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "calories_consumed" in payload
    assert "total_protein" in payload
    assert "total_carbohydrates" in payload
    assert "total_fats" in payload
    assert "meals" in payload
    assert isinstance(payload["meals"], list)
    assert payload["calories_consumed"] >= 0
    assert payload["total_protein"] >= 0
    assert payload["total_carbohydrates"] >= 0
    assert payload["total_fats"] >= 0
    assert "daily_weight" in payload
    assert "latest_weight" in payload
    assert "weight_trend" in payload
    assert len(payload["weight_trend"]) == 6


def test_log_meal_with_explicit_macros(client: TestClient) -> None:
    response = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={
            "food_name": "Macro meal",
            "protein": 30.0,
            "carbohydrates": 40.0,
            "fats": 10.0,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["protein"] == 30.0
    assert body["carbohydrates"] == 40.0
    assert body["fats"] == 10.0
    assert body["calories"] == 370.0
    assert body["ai_estimated"] is False


def test_summary_includes_macro_totals(client: TestClient) -> None:
    first = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={
            "food_name": "Breakfast",
            "protein": 20.0,
            "carbohydrates": 30.0,
            "fats": 5.0,
        },
    )
    second = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={
            "food_name": "Lunch",
            "protein": 10.0,
            "carbohydrates": 15.0,
            "fats": 8.0,
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201

    summary = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_protein"] == 30.0
    assert payload["total_carbohydrates"] == 45.0
    assert payload["total_fats"] == 13.0


def test_activity_summary_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "calories_burned" in payload
    assert "workouts" in payload
    assert isinstance(payload["workouts"], list)
    assert payload["calories_burned"] >= 0


@patch(
    "main.estimate_meal_calories",
    return_value=CalorieEstimate(
        calories=400.0,
        explanation="test",
        ai_estimated=False,
        protein=25.0,
        carbohydrates=40.0,
        fats=12.0,
    ),
)
def test_log_meal_reuses_prior_food_nutrition(mock_estimate, client: TestClient) -> None:
    first = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={"food_name": "Greek yogurt bowl"},
    )
    assert first.status_code == 201
    assert first.json()["calories"] == 400.0
    assert first.json()["protein"] == 25.0
    mock_estimate.assert_called_once()

    mock_estimate.reset_mock()
    second = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={"food_name": "greek yogurt bowl"},
    )
    assert second.status_code == 201
    assert second.json()["calories"] == 400.0
    assert second.json()["protein"] == 25.0
    assert second.json()["carbohydrates"] == 40.0
    assert second.json()["fats"] == 12.0
    assert second.json()["ai_estimated"] is False
    assert "Reusing" in second.json()["ai_explanation"]
    mock_estimate.assert_not_called()


@patch(
    "main.estimate_meal_calories",
    return_value=CalorieEstimate(calories=400.0, explanation="test", ai_estimated=False),
)
def test_log_meal_endpoint_returns_success(mock_estimate, client: TestClient) -> None:
    response = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={"food_name": "Sanity meal"},
    )

    assert response.status_code == 201
    assert response.json()["food_name"] == "Sanity meal"
    mock_estimate.assert_called_once()


@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=200.0, explanation="test", ai_estimated=False),
)
def test_log_workout_endpoint_returns_success(mock_estimate, client: TestClient) -> None:
    response = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "Sanity walk"},
    )

    assert response.status_code == 201
    assert response.json()["activity_type"] == "Sanity walk"
    mock_estimate.assert_called_once()


@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=280.0, explanation="AI estimate", ai_estimated=True),
)
def test_log_workout_reuses_prior_activity_calories(mock_estimate, client: TestClient) -> None:
    first = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "Morning run"},
    )
    assert first.status_code == 201
    assert first.json()["calories_burned"] == 280.0
    mock_estimate.assert_called_once()

    mock_estimate.reset_mock()
    second = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "morning run"},
    )
    assert second.status_code == 201
    assert second.json()["calories_burned"] == 280.0
    assert second.json()["ai_estimated"] is False
    assert "Reusing" in second.json()["ai_explanation"]
    mock_estimate.assert_not_called()


def test_normalize_activity_type_unifies_hebrew_quotes() -> None:
    from main import _normalize_activity_type

    ascii_quotes = _normalize_activity_type('הליכה 4 ק"מ, 50 דקות')
    hebrew_quotes = _normalize_activity_type("הליכה 4 ק\u05f4מ, 50 דקות")
    assert ascii_quotes == hebrew_quotes


@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=278.4, explanation="AI estimate", ai_estimated=True),
)
def test_log_workout_reuses_hebrew_activity_with_different_quotes(
    mock_estimate, client: TestClient
) -> None:
    first = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": 'הליכה 4 ק"מ, 50 דקות'},
    )
    assert first.status_code == 201
    mock_estimate.assert_called_once()

    mock_estimate.reset_mock()
    second = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "הליכה 4 ק\u05f4מ, 50 דקות"},
    )
    assert second.status_code == 201
    assert second.json()["ai_estimated"] is False
    assert second.json()["calories_burned"] == 278.4
    mock_estimate.assert_not_called()


@patch("steps_calories._gemini_steps_calories")
@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=200.0, explanation="AI estimate", ai_estimated=True),
)
def test_add_workout_refreshes_steps_locally_without_ai(
    mock_workout_estimate, mock_gemini_steps, client: TestClient
) -> None:
    today = date.today().isoformat()
    steps_response = client.put(
        f"/api/steps?date={today}",
        headers=client.auth_headers,
        json={"steps_count": 8000},
    )
    assert steps_response.status_code == 200

    workout_response = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "Evening walk"},
    )
    assert workout_response.status_code == 201
    mock_gemini_steps.assert_not_called()


@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=280.0, explanation="AI estimate", ai_estimated=True),
)
def test_update_workout_reuses_prior_activity_when_renamed(mock_estimate, client: TestClient) -> None:
    first = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "Morning run"},
    )
    assert first.status_code == 201
    mock_estimate.assert_called_once()

    second = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "Evening walk"},
    )
    assert second.status_code == 201
    workout_id = second.json()["id"]
    assert mock_estimate.call_count == 2

    mock_estimate.reset_mock()
    rename_response = client.put(
        f"/api/workouts/{workout_id}",
        headers=client.auth_headers,
        json={"activity_type": "Morning run"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["calories_burned"] == 280.0
    assert rename_response.json()["ai_estimated"] is False
    mock_estimate.assert_not_called()


@patch(
    "main.estimate_meal_calories",
    return_value=CalorieEstimate(calories=400.0, explanation="test", ai_estimated=False),
)
def test_delete_meal_endpoint_returns_success(mock_estimate, client: TestClient) -> None:
    create_response = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={"food_name": "Meal to delete"},
    )
    assert create_response.status_code == 201
    meal_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/meals/{meal_id}",
        headers=client.auth_headers,
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    summary_response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )
    meal_ids = [meal["id"] for meal in summary_response.json()["meals"]]
    assert meal_id not in meal_ids


def test_delete_meal_not_found_returns_404(client: TestClient) -> None:
    response = client.delete("/api/meals/999999", headers=client.auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Meal not found"


@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=200.0, explanation="test", ai_estimated=False),
)
def test_delete_workout_endpoint_returns_success(mock_estimate, client: TestClient) -> None:
    create_response = client.post(
        "/api/workouts",
        headers=client.auth_headers,
        json={"activity_type": "Workout to delete"},
    )
    assert create_response.status_code == 201
    workout_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/workouts/{workout_id}",
        headers=client.auth_headers,
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    summary_response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )
    workout_ids = [workout["id"] for workout in summary_response.json()["workouts"]]
    assert workout_id not in workout_ids


def test_delete_workout_not_found_returns_404(client: TestClient) -> None:
    response = client.delete("/api/workouts/999999", headers=client.auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Workout not found"


@patch(
    "main.estimate_steps_calories",
    return_value=StepsCalorieEstimate(
        calories_burned=120.0,
        explanation="test",
        ai_estimated=False,
    ),
)
def test_steps_upsert_updates_existing_record(mock_estimate, client: TestClient) -> None:
    target_date = date.today().isoformat()
    first = client.put(
        f"/api/steps?date={target_date}",
        headers=client.auth_headers,
        json={"steps_count": 5000},
    )
    second = client.put(
        f"/api/steps?date={target_date}",
        headers=client.auth_headers,
        json={"steps_count": 8000},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["daily_steps"]["steps_count"] == 8000
    assert mock_estimate.call_count == 2


def test_weight_upsert_and_summary_trend(client: TestClient) -> None:
    target_date = date.today().isoformat()
    response = client.put(
        f"/api/weight?date={target_date}",
        headers=client.auth_headers,
        json={"weight_kg": 74.5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["daily_weight"]["weight_kg"] == 74.5
    assert body["latest_weight"]["weight_kg"] == 74.5
    assert len(body["weight_trend"]) == 6
    assert body["weight_trend"][-1]["weight_kg"] == 74.5

    summary = client.get(
        f"/api/summary?date={target_date}",
        headers=client.auth_headers,
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["daily_weight"]["weight_kg"] == 74.5
    assert payload["latest_weight"]["weight_kg"] == 74.5
    assert len(payload["weight_trend"]) == 6
    assert payload["weight_trend"][-1]["date"] == target_date


def test_latest_weight_carried_forward_to_later_day(client: TestClient) -> None:
    from datetime import timedelta

    logged_date = (date.today() - timedelta(days=2)).isoformat()
    view_date = date.today().isoformat()

    log_response = client.put(
        f"/api/weight?date={logged_date}",
        headers=client.auth_headers,
        json={"weight_kg": 72.3},
    )
    assert log_response.status_code == 200

    summary = client.get(
        f"/api/summary?date={view_date}",
        headers=client.auth_headers,
    )
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["daily_weight"] is None
    assert payload["latest_weight"]["weight_kg"] == 72.3
    assert payload["latest_weight"]["logged_on_selected_date"] is False
    assert payload["latest_weight"]["source"] == "daily"


def test_latest_weight_uses_registration_baseline_without_daily_log(client: TestClient) -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "username": "baselineuser",
            "password": "secret123",
            "name": "Baseline User",
            "gender": "female",
            "birth_date": (date.today() - timedelta(days=365 * 28)).isoformat(),
            "height_cm": 162.0,
            "weight_kg": 68.2,
        },
    )
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    summary = client.get("/api/summary", headers=headers)
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["daily_weight"] is None
    assert payload["latest_weight"]["weight_kg"] == 68.2
    assert payload["latest_weight"]["source"] == "initial"
    assert payload["latest_weight"]["logged_on_selected_date"] is False
    assert payload["weight_trend"][-1]["weight_kg"] == 68.2


def test_logged_at_round_trip_uses_utc_and_local_day_filter(client: TestClient) -> None:
    logged_at_utc = "2026-07-04T21:30:00.000Z"
    local_date = "2026-07-05"
    tz_offset = -180

    create_response = client.post(
        "/api/meals",
        headers=client.auth_headers,
        json={
            "food_name": "Late-night snack",
            "calories": 120.0,
            "logged_at": logged_at_utc,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["logged_at"] == "2026-07-04T21:30:00Z"

    summary_response = client.get(
        f"/api/summary?date={local_date}&tz_offset={tz_offset}",
        headers=client.auth_headers,
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert any(meal["food_name"] == "Late-night snack" for meal in summary["meals"])
    assert summary["meals"][0]["logged_at"].endswith("Z")

    dates_response = client.get(
        f"/api/dates-with-data?tz_offset={tz_offset}",
        headers=client.auth_headers,
    )
    assert dates_response.status_code == 200
    assert local_date in dates_response.json()["dates"]


def test_summary_meals_and_workouts_logged_at_use_utc_suffix(client: TestClient) -> None:
    response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()

    for meal in payload["meals"]:
        assert meal["logged_at"].endswith("Z")
    for workout in payload["workouts"]:
        assert workout["logged_at"].endswith("Z")
