from datetime import date, datetime

from logged_at_utils import (
    day_bounds_for_local_date,
    format_logged_at_iso,
    local_date_from_logged_at,
    normalize_logged_at_to_utc_naive,
)


def test_format_logged_at_iso_appends_z_for_naive_utc() -> None:
    logged_at = datetime(2026, 7, 5, 11, 0, 0)
    assert format_logged_at_iso(logged_at) == "2026-07-05T11:00:00Z"


def test_day_bounds_for_local_date_utc_plus_three() -> None:
    target = date(2026, 7, 5)
    tz_offset = -180

    day_start, day_end = day_bounds_for_local_date(target, tz_offset)

    assert day_start == datetime(2026, 7, 4, 21, 0, 0)
    assert day_end == datetime(2026, 7, 5, 20, 59, 59, 999999)


def test_local_date_from_logged_at_utc_plus_three() -> None:
    logged_at = datetime(2026, 7, 4, 21, 30, 0)
    assert local_date_from_logged_at(logged_at, -180) == date(2026, 7, 5)


def test_normalize_logged_at_to_utc_naive_strips_offset() -> None:
    from datetime import timezone, timedelta

    aware = datetime(2026, 7, 5, 11, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    assert normalize_logged_at_to_utc_naive(aware) == datetime(2026, 7, 5, 8, 0, 0)
