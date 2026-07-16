"""Full-site export and import for admin backup."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from user_data_io import EXPORT_VERSION, build_export_payload

SITE_EXPORT_VERSION = 1


def build_site_export(db: Session) -> dict:
    from models import User

    users = db.query(User).order_by(User.id.asc()).all()
    return {
        "site_export_version": SITE_EXPORT_VERSION,
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "user_count": len(users),
        "users": [
            {
                "username": user.username,
                "is_admin": bool(user.is_admin),
                "is_active": bool(user.is_active),
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "data": build_export_payload(user, db),
            }
            for user in users
        ],
    }


def export_site_json(db: Session) -> str:
    return json.dumps(build_site_export(db), ensure_ascii=False, indent=2)


def import_site_json(db: Session, payload: dict) -> dict:
    from auth import hash_password
    from models import User
    from user_data_io import apply_import

    if not isinstance(payload, dict):
        raise ValueError("Invalid site export payload")
    users_payload = payload.get("users")
    if not isinstance(users_payload, list):
        raise ValueError("Site export must include a users array")

    imported_users = 0
    skipped_users = 0
    totals = {
        "meals_imported": 0,
        "workouts_imported": 0,
        "steps_upserted": 0,
        "weights_upserted": 0,
    }

    for entry in users_payload:
        username = str(entry.get("username") or "").strip().lower()
        user_data = entry.get("data")
        if not username or not isinstance(user_data, dict):
            skipped_users += 1
            continue

        user = db.query(User).filter(User.username == username).first()
        if user is None:
            profile = user_data.get("profile") or {}
            user = User(
                username=username,
                password_hash=hash_password("ChangeMe123!"),
                name=str(profile.get("name") or username),
                email=profile.get("email"),
                gender=profile.get("gender"),
                is_admin=bool(entry.get("is_admin")),
                is_active=bool(entry.get("is_active", True)),
            )
            db.add(user)
            db.flush()
            imported_users += 1
        else:
            skipped_users += 1

        result = apply_import(user, db, user_data, mode="overwrite", resolutions={})
        totals["meals_imported"] += result.meals_imported
        totals["workouts_imported"] += result.workouts_imported
        totals["steps_upserted"] += result.steps_upserted
        totals["weights_upserted"] += result.weights_upserted

    db.commit()
    return {
        "imported_users": imported_users,
        "skipped_users": skipped_users,
        **totals,
    }
