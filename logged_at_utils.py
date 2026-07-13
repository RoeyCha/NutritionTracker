from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone


def normalize_logged_at_to_utc_naive(logged_at: datetime) -> datetime:
    if logged_at.tzinfo is not None:
        return logged_at.astimezone(timezone.utc).replace(tzinfo=None)
    return logged_at


def format_logged_at_iso(logged_at: datetime) -> str:
    return f"{normalize_logged_at_to_utc_naive(logged_at).isoformat()}Z"


def day_bounds_for_local_date(
    target_date: date,
    tz_offset_minutes: int | None = None,
) -> tuple[datetime, datetime]:
    if tz_offset_minutes is None:
        return (
            datetime.combine(target_date, dt_time.min),
            datetime.combine(target_date, dt_time.max),
        )

    local_start = datetime.combine(target_date, dt_time.min)
    local_end = datetime.combine(target_date, dt_time.max)
    return (
        local_start + timedelta(minutes=tz_offset_minutes),
        local_end + timedelta(minutes=tz_offset_minutes),
    )


def local_date_from_logged_at(
    logged_at: datetime,
    tz_offset_minutes: int | None = None,
) -> date:
    if tz_offset_minutes is None:
        return logged_at.date()
    return (logged_at - timedelta(minutes=tz_offset_minutes)).date()
