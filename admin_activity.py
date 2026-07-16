"""Authentication activity logging for admin audit."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from models import AuthActivityLog, User


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return None


def _user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    value = request.headers.get("user-agent")
    return value[:300] if value else None


def log_auth_event(
    db: Session,
    event: str,
    *,
    user: User | None = None,
    username: str | None = None,
    request: Request | None = None,
    details: str | None = None,
) -> None:
    db.add(
        AuthActivityLog(
            user_id=user.id if user else None,
            username=(username or (user.username if user else None)),
            event=event,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            details=details,
        )
    )


def auth_activity_to_dict(row: AuthActivityLog) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "username": row.username,
        "event": row.event,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "details": row.details,
        "created_at": row.created_at.isoformat(),
    }
