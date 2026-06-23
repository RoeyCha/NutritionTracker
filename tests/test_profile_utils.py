from datetime import date, timedelta

from profile_utils import age_years_from_birth_date, validate_birth_date


def test_age_years_from_birth_date() -> None:
    birth_date = date(2000, 6, 22)
    assert age_years_from_birth_date(birth_date, as_of=date(2026, 6, 21)) == 25
    assert age_years_from_birth_date(birth_date, as_of=date(2026, 6, 22)) == 26


def test_validate_birth_date_rejects_future() -> None:
    try:
        validate_birth_date(date.today() + timedelta(days=1))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "future" in str(exc).lower()
