import json
from datetime import datetime

from admin_site_io import build_site_export, import_site_json
from auth import hash_password
from models import Meal, User, Workout
from user_data_io import build_export_payload


def test_build_site_export_includes_users(empty_client) -> None:
    db = empty_client.db_session
    user = User(
        username="export_user",
        password_hash=hash_password("testpass"),
        name="Export User",
        is_admin=False,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(
        Meal(
            user_id=user.id,
            food_name="Exported meal",
            calories=400,
            logged_at=datetime.utcnow(),
        )
    )
    db.commit()

    payload = build_site_export(db)
    assert payload["site_export_version"] == 1
    assert payload["user_count"] >= 1
    exported = next(item for item in payload["users"] if item["username"] == "export_user")
    assert exported["is_active"] is True
    assert exported["data"]["meals"]


def test_import_site_json_creates_new_user(empty_client) -> None:
    db = empty_client.db_session
    user = User(
        username="source_user",
        password_hash=hash_password("testpass"),
        name="Source User",
    )
    db.add(user)
    db.flush()
    db.add(
        Workout(
            user_id=user.id,
            activity_type="Run",
            calories_burned=200,
            logged_at=datetime.utcnow(),
        )
    )
    db.commit()

    site_payload = build_site_export(db)
    site_payload["users"] = [
        entry for entry in site_payload["users"] if entry["username"] != "source_user"
    ]
    site_payload["users"].append(
        {
            "username": "imported_user",
            "is_admin": False,
            "is_active": True,
            "data": build_export_payload(user, db),
        }
    )

    summary = import_site_json(db, site_payload)
    assert summary["imported_users"] == 1
    assert summary["workouts_imported"] >= 1

    imported = db.query(User).filter(User.username == "imported_user").first()
    assert imported is not None
    assert db.query(Workout).filter(Workout.user_id == imported.id).count() == 1


def test_import_site_json_rejects_invalid_payload(empty_client) -> None:
    db = empty_client.db_session
    try:
        import_site_json(db, {"not_users": []})
        raised = False
    except ValueError as exc:
        raised = True
        assert "users array" in str(exc)
    assert raised
