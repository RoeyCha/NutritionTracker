"""Track AI API usage for admin metrics."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from models import AiCallLog, SessionLocal


def record_ai_call(
    *,
    feature: str,
    user_id: int | None = None,
    model: str | None = None,
    success: bool,
    error_message: str | None = None,
    request_bytes: int = 0,
    response_bytes: int = 0,
    duration_ms: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        db.add(
            AiCallLog(
                user_id=user_id,
                feature=feature,
                model=model,
                success=success,
                error_message=(error_message or "")[:500] or None,
                request_bytes=max(0, request_bytes),
                response_bytes=max(0, response_bytes),
                duration_ms=duration_ms,
            )
        )
        db.commit()
    finally:
        db.close()


def build_ai_metrics(db: Session, days: int = 7) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(
            func.date(AiCallLog.created_at).label("day"),
            func.count(AiCallLog.id).label("total"),
            func.sum(case((AiCallLog.success.is_(True), 1), else_=0)).label("success_count"),
            func.sum(AiCallLog.request_bytes).label("request_bytes"),
            func.sum(AiCallLog.response_bytes).label("response_bytes"),
        )
        .filter(AiCallLog.created_at >= since)
        .group_by(func.date(AiCallLog.created_at))
        .order_by(func.date(AiCallLog.created_at))
        .all()
    )
    daily = []
    for row in rows:
        total = int(row.total or 0)
        success_count = int(row.success_count or 0)
        daily.append(
            {
                "date": str(row.day),
                "total_calls": total,
                "success_calls": success_count,
                "failure_calls": total - success_count,
                "request_bytes": int(row.request_bytes or 0),
                "response_bytes": int(row.response_bytes or 0),
            }
        )
    totals = (
        db.query(
            func.count(AiCallLog.id),
            func.sum(case((AiCallLog.success.is_(True), 1), else_=0)),
            func.sum(AiCallLog.request_bytes),
            func.sum(AiCallLog.response_bytes),
        )
        .filter(AiCallLog.created_at >= since)
        .one()
    )
    total_calls = int(totals[0] or 0)
    success_calls = int(totals[1] or 0)
    return {
        "days": days,
        "daily": daily,
        "totals": {
            "total_calls": total_calls,
            "success_calls": success_calls,
            "failure_calls": total_calls - success_calls,
            "request_bytes": int(totals[2] or 0),
            "response_bytes": int(totals[3] or 0),
        },
    }
