"""Helpers for user profile fields used across the app."""

from datetime import date, timedelta

from models import User

MAX_PROFILE_AGE_YEARS = 120


def age_years_from_birth_date(birth_date: date | None, as_of: date | None = None) -> int | None:
    """Return whole years between ``birth_date`` and ``as_of`` (default today)."""
    if birth_date is None:
        return None

    today = as_of or date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def validate_birth_date(value: date | None) -> date | None:
    """Validate an optional birth date for profile registration/update."""
    if value is None:
        return None

    today = date.today()
    if value > today:
        raise ValueError("Birth date cannot be in the future")

    min_date = today - timedelta(days=365 * MAX_PROFILE_AGE_YEARS)
    if value < min_date:
        raise ValueError("Birth date is too far in the past")

    return value


def profile_height_cm(user: User) -> float | None:
    """Return the user's height in cm, if recorded on the profile."""
    if user.height_cm is None:
        return None
    return float(user.height_cm)


def user_age_for_calculations(user: User, as_of: date | None = None) -> int | None:
    """Return the user's age in years for calorie and BMR calculations."""
    return age_years_from_birth_date(user.birth_date, as_of=as_of)
