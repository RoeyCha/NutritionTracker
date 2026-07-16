"""Runtime and persisted application settings."""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy.orm import Session

from models import AppSetting, SessionLocal

GEMINI_API_KEY_SETTING = "gemini_api_key"
_runtime_gemini_api_key: str | None = None


def get_gemini_api_key() -> str | None:
    if _runtime_gemini_api_key:
        return _runtime_gemini_api_key
    return os.getenv("GEMINI_API_KEY")


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def load_settings_from_db(db: Session | None = None) -> None:
    global _runtime_gemini_api_key
    owns_session = db is None
    session = db or SessionLocal()
    try:
        row = session.get(AppSetting, GEMINI_API_KEY_SETTING)
        if row and row.value:
            _runtime_gemini_api_key = row.value
    finally:
        if owns_session:
            session.close()


def set_gemini_api_key(db: Session, api_key: str | None) -> None:
    global _runtime_gemini_api_key
    cleaned = (api_key or "").strip() or None
    row = db.get(AppSetting, GEMINI_API_KEY_SETTING)
    if row is None:
        row = AppSetting(key=GEMINI_API_KEY_SETTING)
        db.add(row)
    row.value = cleaned
    row.updated_at = datetime.utcnow()
    _runtime_gemini_api_key = cleaned


def gemini_api_key_status(db: Session) -> dict:
    row = db.get(AppSetting, GEMINI_API_KEY_SETTING)
    effective = get_gemini_api_key()
    source = "database" if row and row.value else ("environment" if os.getenv("GEMINI_API_KEY") else "none")
    return {
        "configured": bool(effective),
        "masked_key": mask_secret(effective),
        "source": source,
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }
