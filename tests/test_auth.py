from datetime import date, timedelta

from fastapi.testclient import TestClient

from auth import create_access_token, hash_password
from models import User

def test_register_without_email(empty_client: TestClient) -> None:
    response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "no_email_user",
            "password": "testpass",
            "name": "No Email User",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["user"]["username"] == "no_email_user"
    assert payload["user"]["email"] is None
    assert payload["access_token"]


def test_register_with_email_and_profile(empty_client: TestClient) -> None:
    birth_date = date(1998, 3, 15).isoformat()
    response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "full_profile",
            "password": "testpass",
            "name": "Full Profile",
            "email": "full@example.com",
            "gender": "female",
            "birth_date": birth_date,
            "height_cm": 165.0,
            "weight_kg": 62.5,
        },
    )

    assert response.status_code == 201
    user = response.json()["user"]
    assert user["email"] == "full@example.com"
    assert user["gender"] == "female"
    assert user["birth_date"] == birth_date
    assert user["height_cm"] == 165.0
    assert user["weight_kg"] == 62.5
    assert user["age"] == date.today().year - 1998 - (
        1 if (date.today().month, date.today().day) < (3, 15) else 0
    )


def test_register_duplicate_username_returns_409(empty_client: TestClient) -> None:
    payload = {
        "username": "duplicate_user",
        "password": "testpass",
        "name": "First User",
    }
    assert empty_client.post("/api/auth/register", json=payload).status_code == 201

    response = empty_client.post("/api/auth/register", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Username already taken"


def test_register_duplicate_email_returns_409(empty_client: TestClient) -> None:
    email = "shared@example.com"
    assert (
        empty_client.post(
            "/api/auth/register",
            json={
                "username": "user_one",
                "password": "testpass",
                "name": "User One",
                "email": email,
            },
        ).status_code
        == 201
    )

    response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "user_two",
            "password": "testpass",
            "name": "User Two",
            "email": email,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_register_invalid_username_returns_422(empty_client: TestClient) -> None:
    response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "bad user!",
            "password": "testpass",
            "name": "Bad Username",
        },
    )

    assert response.status_code == 422


def test_register_short_password_returns_422(empty_client: TestClient) -> None:
    response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "shortpw",
            "password": "abc",
            "name": "Short Password",
        },
    )

    assert response.status_code == 422


def test_login_success(empty_client: TestClient) -> None:
    empty_client.post(
        "/api/auth/register",
        json={
            "username": "login_user",
            "password": "secret1234",
            "name": "Login User",
        },
    )

    response = empty_client.post(
        "/api/auth/login",
        json={"username": "login_user", "password": "secret1234"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["username"] == "login_user"
    assert payload["access_token"]


def test_register_and_me_include_admin_flags(empty_client: TestClient) -> None:
    register = empty_client.post(
        "/api/auth/register",
        json={
            "username": "flags_user",
            "password": "testpass",
            "name": "Flags User",
        },
    )
    assert register.status_code == 201
    user = register.json()["user"]
    assert user["is_admin"] is False
    assert user["is_active"] is True

    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}
    me = empty_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["is_admin"] is False
    assert me.json()["is_active"] is True


def test_inactive_user_token_rejected_on_protected_route(empty_client: TestClient) -> None:
    user = User(
        username="blocked_token_user",
        password_hash=hash_password("testpass"),
        name="Blocked",
        is_active=False,
    )
    empty_client.db_session.add(user)
    empty_client.db_session.commit()

    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    response = empty_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Account deactivated"


def test_login_invalid_password_returns_401(empty_client: TestClient) -> None:
    empty_client.post(
        "/api/auth/register",
        json={
            "username": "wrong_pw_user",
            "password": "correctpass",
            "name": "Wrong Password",
        },
    )

    response = empty_client.post(
        "/api/auth/login",
        json={"username": "wrong_pw_user", "password": "wrongpass"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_auth_me_requires_token(empty_client: TestClient) -> None:
    response = empty_client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_profile_update_clears_email(empty_client: TestClient) -> None:
    register_response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "profile_user",
            "password": "testpass",
            "name": "Profile User",
            "email": "profile@example.com",
        },
    )
    token = register_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = empty_client.put(
        "/api/profile",
        headers=headers,
        json={
            "name": "Profile User",
            "email": None,
            "gender": None,
            "birth_date": None,
            "height_cm": None,
            "weight_kg": None,
        },
    )

    assert response.status_code == 200
    assert response.json()["email"] is None


def test_profile_update_birth_date_and_height(empty_client: TestClient) -> None:
    register_response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "profile_fields",
            "password": "testpass",
            "name": "Profile Fields",
        },
    )
    token = register_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    birth_date = date(1990, 7, 4).isoformat()

    response = empty_client.put(
        "/api/profile",
        headers=headers,
        json={
            "name": "Profile Fields",
            "email": None,
            "gender": "male",
            "birth_date": birth_date,
            "height_cm": 178.5,
            "weight_kg": 80.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["birth_date"] == birth_date
    assert payload["height_cm"] == 178
    assert payload["weight_kg"] == 80.0
    assert payload["bmr"] is not None
