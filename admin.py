"""Admin dashboard API routes."""

from __future__ import annotations

import os
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from admin_activity import auth_activity_to_dict, log_auth_event
from admin_site_io import build_site_export, export_site_json, import_site_json
from ai_metrics import build_ai_metrics
from app_settings import gemini_api_key_status, set_gemini_api_key
from auth import get_current_admin, get_db, hash_password, user_to_dict
from models import (
    AuthActivityLog,
    DailySteps,
    DailyWeight,
    Meal,
    User,
    Workout,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

APP_START_MONOTONIC = time.monotonic()
APP_START_AT = datetime.utcnow()


class ResetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=4, max_length=128)


class GeminiKeyUpdate(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=500)


class SiteImportRequest(BaseModel):
    content: str = Field(..., min_length=2)


def _user_admin_dict(user: User, db: Session) -> dict:
    meal_count = db.query(func.count(Meal.id)).filter(Meal.user_id == user.id).scalar() or 0
    workout_count = db.query(func.count(Workout.id)).filter(Workout.user_id == user.id).scalar() or 0
    return {
        **user_to_dict(user),
        "is_admin": bool(user.is_admin),
        "is_active": bool(user.is_active),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "meal_count": int(meal_count),
        "workout_count": int(workout_count),
    }


def _database_size_bytes() -> int:
    path = "nutrition_tracker.db"
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


@router.get("/metrics")
def admin_metrics(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    admin_users = db.query(func.count(User.id)).filter(User.is_admin.is_(True)).scalar() or 0
    return {
        "uptime_seconds": int(time.monotonic() - APP_START_MONOTONIC),
        "started_at": APP_START_AT.isoformat(),
        "users": {
            "total": int(total_users),
            "active": int(active_users),
            "inactive": int(total_users) - int(active_users),
            "admins": int(admin_users),
        },
        "records": {
            "meals": int(db.query(func.count(Meal.id)).scalar() or 0),
            "workouts": int(db.query(func.count(Workout.id)).scalar() or 0),
            "daily_steps": int(db.query(func.count(DailySteps.id)).scalar() or 0),
            "daily_weights": int(db.query(func.count(DailyWeight.id)).scalar() or 0),
        },
        "database_size_bytes": _database_size_bytes(),
        "gemini": gemini_api_key_status(db),
        "ai": build_ai_metrics(db),
    }


@router.get("/users")
def list_users(
    search: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    query = db.query(User)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(User.username).like(term),
                func.lower(User.name).like(term),
                func.lower(User.email).like(term),
            )
        )
    if active is not None:
        query = query.filter(User.is_active.is_(active))
    users = query.order_by(User.created_at.desc()).all()
    return {"users": [_user_admin_dict(user, db) for user in users]}


@router.get("/activity")
def list_activity(
    user_id: int | None = Query(default=None),
    event: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    query = db.query(AuthActivityLog)
    if user_id is not None:
        query = query.filter(AuthActivityLog.user_id == user_id)
    if event:
        query = query.filter(AuthActivityLog.event == event.strip().lower())
    rows = query.order_by(AuthActivityLog.created_at.desc()).limit(limit).all()
    return {"activity": [auth_activity_to_dict(row) for row in rows]}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.password_hash = hash_password(payload.password)
    db.commit()
    log_auth_event(
        db,
        "password_reset",
        user=user,
        request=request,
        details=f"Reset by admin {admin.username}",
    )
    db.commit()
    return {"ok": True}


@router.patch("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = False
    log_auth_event(
        db,
        "deactivated",
        user=user,
        request=request,
        details=f"Deactivated by admin {admin.username}",
    )
    db.commit()
    return {"ok": True, "user": _user_admin_dict(user, db)}


@router.patch("/users/{user_id}/activate")
def activate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.is_active = True
    log_auth_event(
        db,
        "activated",
        user=user,
        request=request,
        details=f"Activated by admin {admin.username}",
    )
    db.commit()
    return {"ok": True, "user": _user_admin_dict(user, db)}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete admin users")
    username = user.username
    db.delete(user)
    log_auth_event(
        db,
        "deleted",
        username=username,
        request=request,
        details=f"Deleted by admin {admin.username}",
    )
    db.commit()
    return {"ok": True}


@router.get("/settings/gemini")
def get_gemini_settings(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    return gemini_api_key_status(db)


@router.put("/settings/gemini")
def update_gemini_settings(
    payload: GeminiKeyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    set_gemini_api_key(db, payload.api_key.strip())
    log_auth_event(
        db,
        "gemini_key_updated",
        user=admin,
        request=request,
        details="Gemini API key updated",
    )
    db.commit()
    return gemini_api_key_status(db)


@router.get("/export/site")
def export_site(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    payload = build_site_export(db)
    return payload


@router.get("/export/site/download")
def export_site_download(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    del admin
    from fastapi.responses import Response

    content = export_site_json(db)
    filename = f"nutrition-tracker-site-{datetime.utcnow().strftime('%Y%m%d')}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/site")
def import_site(
    payload: SiteImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    import json

    try:
        parsed = json.loads(payload.content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid JSON") from exc
    try:
        summary = import_site_json(db, parsed)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    log_auth_event(
        db,
        "site_import",
        user=admin,
        request=request,
        details=f"Imported {summary.get('imported_users', 0)} users",
    )
    db.commit()
    return summary
