from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_calories import CalorieEstimate


def _register_user(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "testpass",
            "name": username.title(),
        },
    )
    assert response.status_code == 201
    return response.json()


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@patch(
    "main.estimate_meal_calories",
    return_value=CalorieEstimate(calories=400.0, explanation="test", ai_estimated=False),
)
def test_cannot_delete_other_users_meal(mock_estimate, empty_client: TestClient) -> None:
    owner = _register_user(empty_client, "meal_owner")
    intruder = _register_user(empty_client, "meal_intruder")

    create_response = empty_client.post(
        "/api/meals",
        headers=_auth_headers(owner["access_token"]),
        json={"food_name": "Owner meal"},
    )
    assert create_response.status_code == 201
    meal_id = create_response.json()["id"]

    delete_response = empty_client.delete(
        f"/api/meals/{meal_id}",
        headers=_auth_headers(intruder["access_token"]),
    )

    assert delete_response.status_code == 404
    assert delete_response.json()["detail"] == "Meal not found"


@patch(
    "main.estimate_workout_calories",
    return_value=CalorieEstimate(calories=200.0, explanation="test", ai_estimated=False),
)
def test_cannot_update_other_users_workout(mock_estimate, empty_client: TestClient) -> None:
    owner = _register_user(empty_client, "workout_owner")
    intruder = _register_user(empty_client, "workout_intruder")

    create_response = empty_client.post(
        "/api/workouts",
        headers=_auth_headers(owner["access_token"]),
        json={"activity_type": "Owner run"},
    )
    assert create_response.status_code == 201
    workout_id = create_response.json()["id"]

    update_response = empty_client.put(
        f"/api/workouts/{workout_id}",
        headers=_auth_headers(intruder["access_token"]),
        json={"activity_type": "Stolen run"},
    )

    assert update_response.status_code == 404
    assert update_response.json()["detail"] == "Workout not found"


def test_cors_allows_configured_origin(empty_client: TestClient) -> None:
    response = empty_client.options(
        "/api/capabilities",
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"


def test_cors_rejects_unknown_origin(empty_client: TestClient) -> None:
    response = empty_client.get(
        "/api/capabilities",
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_negative_steps_count_returns_422(client: TestClient) -> None:
    response = client.put(
        f"/api/steps?date={date.today().isoformat()}",
        headers=client.auth_headers,
        json={"steps_count": -100},
    )

    assert response.status_code == 422
