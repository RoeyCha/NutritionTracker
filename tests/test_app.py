from collections.abc import Generator
from datetime import date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ai_calories import CalorieEstimate
from auth import create_access_token, get_db, hash_password
from main import app
from models import Base, Meal, User, Workout


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr("main.init_db", lambda: None)
    monkeypatch.setattr("main.seed_test_user", lambda db: None)

    app.dependency_overrides[get_db] = override_get_db

    db = testing_session_local()
    user = User(
        username="pytest_user",
        password_hash=hash_password("testpass"),
        name="Pytest User",
        gender="male",
        age=30,
        weight_kg=75.0,
        bmr=1700.0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    today = datetime.utcnow()
    db.add(
        Meal(
            user_id=user.id,
            food_name="Test oatmeal",
            calories=350.0,
            logged_at=today,
        )
    )
    db.add(
        Workout(
            user_id=user.id,
            activity_type="Test walk",
            calories_burned=150.0,
            logged_at=today,
        )
    )
    db.commit()

    auth_header = {"Authorization": f"Bearer {create_access_token(user)}"}

    with TestClient(app) as test_client:
        test_client.auth_headers = auth_header
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_home_page_loads(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Nutrition Tracker" in response.text


def test_nutrition_summary_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "calories_consumed" in payload
    assert "meals" in payload
    assert isinstance(payload["meals"], list)
    assert payload["calories_consumed"] >= 0


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
    assert delete_response.json()["id"] == meal_id

    summary_response = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    )
    meal_ids = [meal["id"] for meal in summary_response.json()["meals"]]
    assert meal_id not in meal_ids
