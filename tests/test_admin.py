from fastapi.testclient import TestClient

from auth import create_access_token, hash_password, verify_password
from models import AuthActivityLog, DailySteps, Meal, User, Workout
from seed import seed_admin_user


def _create_admin(db_session, username: str = "administrator") -> User:
    user = User(
        username=username,
        password_hash=hash_password("Admin1234!"),
        name="Admin User",
        is_admin=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _admin_headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_register_admin_username_blocked(empty_client: TestClient) -> None:
    response = empty_client.post(
        "/api/auth/register",
        json={
            "username": "admin",
            "password": "testpass",
            "name": "Fake Admin",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "This username is reserved"


def test_admin_routes_require_admin(empty_client: TestClient) -> None:
    response = empty_client.get("/api/admin/metrics")
    assert response.status_code == 401


def test_non_admin_cannot_access_admin_routes(empty_client: TestClient) -> None:
    register = empty_client.post(
        "/api/auth/register",
        json={
            "username": "regular_user",
            "password": "testpass",
            "name": "Regular User",
        },
    )
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    response = empty_client.get("/api/admin/metrics", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_admin_metrics_and_users(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)

    empty_client.post(
        "/api/auth/register",
        json={
            "username": "member_one",
            "password": "testpass",
            "name": "Member One",
        },
    )

    metrics = empty_client.get("/api/admin/metrics", headers=headers)
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["users"]["total"] >= 2
    assert "uptime_seconds" in payload
    assert "ai" in payload
    assert "gemini" in payload

    users = empty_client.get("/api/admin/users", headers=headers)
    assert users.status_code == 200
    usernames = {user["username"] for user in users.json()["users"]}
    assert "administrator" in usernames
    assert "member_one" in usernames


def test_login_logs_activity_and_blocks_inactive_user(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    member = User(
        username="inactive_user",
        password_hash=hash_password("testpass"),
        name="Inactive User",
        is_active=False,
    )
    empty_client.db_session.add(member)
    empty_client.db_session.commit()

    login = empty_client.post(
        "/api/auth/login",
        json={"username": "inactive_user", "password": "testpass"},
    )
    assert login.status_code == 403

    admin_login = empty_client.post(
        "/api/auth/login",
        json={"username": "administrator", "password": "Admin1234!"},
    )
    assert admin_login.status_code == 200
    assert admin_login.json()["user"]["is_admin"] is True

    headers = _admin_headers(admin)
    activity = empty_client.get("/api/admin/activity", headers=headers)
    events = {row["event"] for row in activity.json()["activity"]}
    assert "login" in events
    assert "login_blocked" in events


def test_admin_user_management(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)

    register = empty_client.post(
        "/api/auth/register",
        json={
            "username": "managed_user",
            "password": "oldpass",
            "name": "Managed User",
        },
    )
    user_id = register.json()["user"]["id"]

    reset = empty_client.post(
        f"/api/admin/users/{user_id}/reset-password",
        headers=headers,
        json={"password": "newpass123"},
    )
    assert reset.status_code == 200

    login = empty_client.post(
        "/api/auth/login",
        json={"username": "managed_user", "password": "newpass123"},
    )
    assert login.status_code == 200

    deactivate = empty_client.patch(f"/api/admin/users/{user_id}/deactivate", headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["user"]["is_active"] is False

    blocked = empty_client.post(
        "/api/auth/login",
        json={"username": "managed_user", "password": "newpass123"},
    )
    assert blocked.status_code == 403

    activate = empty_client.patch(f"/api/admin/users/{user_id}/activate", headers=headers)
    assert activate.status_code == 200

    delete = empty_client.delete(f"/api/admin/users/{user_id}", headers=headers)
    assert delete.status_code == 200
    assert empty_client.db_session.get(User, user_id) is None


def test_admin_cannot_use_tracker_api(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)

    response = empty_client.post(
        "/api/meals",
        headers=headers,
        json={"food_name": "Admin meal", "calories": 100},
    )

    assert response.status_code == 403
    assert "admin dashboard" in response.json()["detail"].lower()


def test_admin_page_loads(empty_client: TestClient) -> None:
    response = empty_client.get("/admin")
    assert response.status_code == 200
    assert "Admin Dashboard" in response.text


def test_logout_logs_activity(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)

    response = empty_client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 200

    rows = (
        empty_client.db_session.query(AuthActivityLog)
        .filter(AuthActivityLog.event == "logout")
        .all()
    )
    assert len(rows) >= 1


def test_seed_admin_user_creates_admin_account(empty_client: TestClient) -> None:
    admin = seed_admin_user(empty_client.db_session)
    assert admin.username == "admin"
    assert admin.is_admin is True
    assert admin.is_active is True
    assert verify_password("Admin1234!", admin.password_hash)


def test_admin_users_search_and_active_filter(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)
    db = empty_client.db_session

    active = User(
        username="active_member",
        password_hash=hash_password("testpass"),
        name="Active Member",
        is_active=True,
    )
    inactive = User(
        username="inactive_member",
        password_hash=hash_password("testpass"),
        name="Inactive Member",
        is_active=False,
    )
    db.add_all([active, inactive])
    db.commit()

    search = empty_client.get("/api/admin/users?search=inactive", headers=headers)
    assert search.status_code == 200
    usernames = {user["username"] for user in search.json()["users"]}
    assert usernames == {"inactive_member"}

    active_only = empty_client.get("/api/admin/users?active=true", headers=headers)
    assert all(user["is_active"] for user in active_only.json()["users"])


def test_admin_activity_filter_by_user(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)
    member = User(
        username="activity_member",
        password_hash=hash_password("testpass"),
        name="Activity Member",
        is_active=True,
    )
    empty_client.db_session.add(member)
    empty_client.db_session.commit()

    empty_client.post(
        "/api/auth/login",
        json={"username": "activity_member", "password": "testpass"},
    )

    response = empty_client.get(
        f"/api/admin/activity?user_id={member.id}&event=login",
        headers=headers,
    )
    assert response.status_code == 200
    rows = response.json()["activity"]
    assert rows
    assert all(row["user_id"] == member.id for row in rows)
    assert all(row["event"] == "login" for row in rows)


def test_admin_update_gemini_key(empty_client: TestClient, monkeypatch) -> None:
    import app_settings

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app_settings._runtime_gemini_api_key = None

    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)

    response = empty_client.put(
        "/api/admin/settings/gemini",
        headers=headers,
        json={"api_key": "admin-set-key-12345"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["source"] == "database"
    assert payload["masked_key"].endswith("2345")


def test_admin_site_export_and_import(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)
    db = empty_client.db_session

    user = User(
        username="site_user",
        password_hash=hash_password("testpass"),
        name="Site User",
    )
    db.add(user)
    db.flush()
    db.add(Meal(user_id=user.id, food_name="Site meal", calories=300))
    db.commit()

    export = empty_client.get("/api/admin/export/site", headers=headers)
    assert export.status_code == 200
    payload = export.json()
    assert payload["user_count"] >= 1
    assert any(entry["username"] == "site_user" for entry in payload["users"])

    download = empty_client.get("/api/admin/export/site/download", headers=headers)
    assert download.status_code == 200
    assert "application/json" in download.headers["content-type"]

    payload["users"] = [
        {
            "username": "restored_user",
            "is_admin": False,
            "is_active": True,
            "data": next(entry["data"] for entry in payload["users"] if entry["username"] == "site_user"),
        }
    ]
    import_response = empty_client.post(
        "/api/admin/import/site",
        headers=headers,
        json={"content": __import__("json").dumps(payload)},
    )
    assert import_response.status_code == 200
    assert import_response.json()["imported_users"] == 1
    assert db.query(User).filter(User.username == "restored_user").first() is not None


def test_admin_delete_cascades_tracker_data(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)
    db = empty_client.db_session

    user = User(
        username="delete_me",
        password_hash=hash_password("testpass"),
        name="Delete Me",
    )
    db.add(user)
    db.flush()
    user_id = user.id
    db.add(Meal(user_id=user_id, food_name="Meal", calories=100))
    db.add(Workout(user_id=user_id, activity_type="Run", calories_burned=50))
    db.add(DailySteps(user_id=user_id, entry_date=__import__("datetime").date.today(), steps_count=1000))
    db.commit()

    response = empty_client.delete(f"/api/admin/users/{user_id}", headers=headers)
    assert response.status_code == 200
    assert db.get(User, user_id) is None
    assert db.query(Meal).filter(Meal.user_id == user_id).count() == 0
    assert db.query(Workout).filter(Workout.user_id == user_id).count() == 0
    assert db.query(DailySteps).filter(DailySteps.user_id == user_id).count() == 0


def test_admin_cannot_delete_self_or_admin_users(empty_client: TestClient) -> None:
    admin = _create_admin(empty_client.db_session)
    headers = _admin_headers(admin)

    self_delete = empty_client.delete(f"/api/admin/users/{admin.id}", headers=headers)
    assert self_delete.status_code == 400

    other_admin = User(
        username="other_admin",
        password_hash=hash_password("Admin1234!"),
        name="Other Admin",
        is_admin=True,
        is_active=True,
    )
    empty_client.db_session.add(other_admin)
    empty_client.db_session.commit()

    admin_delete = empty_client.delete(f"/api/admin/users/{other_admin.id}", headers=headers)
    assert admin_delete.status_code == 400

