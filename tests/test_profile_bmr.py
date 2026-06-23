from datetime import date

from bmr_calculator import calculate_bmr_mifflin_st_jeor
from fastapi.testclient import TestClient
from profile_utils import age_years_from_birth_date

from auth import get_db
from main import app


def _profile_payload(user: dict, **overrides) -> dict:
    payload = {
        "name": user["name"],
        "email": user.get("email"),
        "gender": user.get("gender"),
        "birth_date": user.get("birth_date"),
        "height_cm": user.get("height_cm"),
        "weight_kg": user.get("weight_kg"),
    }
    payload.update(overrides)
    return payload


def test_profile_update_recalculates_bmr_when_weight_changes(client: TestClient) -> None:
    me = client.get("/api/auth/me", headers=client.auth_headers).json()
    initial_bmr = me["bmr"]
    assert initial_bmr is not None

    summary_before = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert summary_before["bmr"] == initial_bmr

    updated = client.put(
        "/api/profile",
        headers=client.auth_headers,
        json=_profile_payload(me, weight_kg=90.0),
    ).json()

    age = age_years_from_birth_date(date.fromisoformat(me["birth_date"]))
    expected_bmr = calculate_bmr_mifflin_st_jeor(
        90.0,
        age,
        gender=me["gender"],
        height_cm=me["height_cm"],
    )

    assert updated["weight_kg"] == 90.0
    assert updated["bmr"] == expected_bmr
    assert updated["bmr"] != initial_bmr
    assert "Mifflin-St Jeor" in updated["bmr_explanation"]

    summary_after = client.get(
        f"/api/summary?date={date.today().isoformat()}",
        headers=client.auth_headers,
    ).json()
    assert summary_after["bmr"] == expected_bmr
    assert summary_after["bmr_explanation"] == updated["bmr_explanation"]


def test_profile_update_recalculates_bmr_when_height_changes(client: TestClient) -> None:
    me = client.get("/api/auth/me", headers=client.auth_headers).json()
    initial_bmr = me["bmr"]
    assert initial_bmr is not None

    updated = client.put(
        "/api/profile",
        headers=client.auth_headers,
        json=_profile_payload(me, height_cm=190.0),
    ).json()

    age = age_years_from_birth_date(date.fromisoformat(me["birth_date"]))
    expected_bmr = calculate_bmr_mifflin_st_jeor(
        me["weight_kg"],
        age,
        gender=me["gender"],
        height_cm=190.0,
    )

    assert updated["height_cm"] == 190.0
    assert updated["bmr"] == expected_bmr
    assert updated["bmr"] != initial_bmr


def test_profile_update_accepts_height_at_minimum(client: TestClient) -> None:
    me = client.get("/api/auth/me", headers=client.auth_headers).json()

    updated = client.put(
        "/api/profile",
        headers=client.auth_headers,
        json=_profile_payload(me, height_cm=50.0),
    )

    assert updated.status_code == 200
    assert updated.json()["height_cm"] == 50.0


def test_auth_me_backfills_missing_bmr(client: TestClient) -> None:
    from models import User

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        user = db.query(User).filter(User.id == client.test_user.id).one()
        user.bmr = None
        user.bmr_explanation = None
        db.commit()
    finally:
        db_gen.close()

    me = client.get("/api/auth/me", headers=client.auth_headers).json()
    assert me["bmr"] is not None
    assert "Mifflin-St Jeor" in me["bmr_explanation"]


def test_profile_update_preserves_birth_date_when_null_sent(empty_client: TestClient) -> None:
    register_response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "bmr_preserve_user",
            "password": "testpass",
            "name": "BMR Preserve User",
            "birth_date": date(1990, 1, 1).isoformat(),
            "height_cm": 175.0,
            "weight_kg": 75.0,
        },
    )
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert register_response.json()["user"]["bmr"] is not None

    updated = empty_client.put(
        "/api/profile",
        headers=headers,
        json={
            "name": "BMR Preserve User",
            "email": None,
            "gender": "male",
            "birth_date": None,
            "height_cm": 180.0,
            "weight_kg": 75.0,
        },
    ).json()

    assert updated["birth_date"] == date(1990, 1, 1).isoformat()
    assert updated["height_cm"] == 180.0
    assert updated["bmr"] is not None
