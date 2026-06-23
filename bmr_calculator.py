"""Local BMR (Basal Metabolic Rate) calculations for user profiles.

BMR is estimated with the Mifflin-St Jeor equation using the user's weight,
age (derived from birth date), gender, and height when available.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from models import User
from profile_utils import profile_height_cm, user_age_for_calculations

# Typical adult heights (cm) used when height is not stored on the profile.
DEFAULT_HEIGHT_CM = {
    "male": 175.0,
    "female": 162.0,
}
DEFAULT_HEIGHT_CM_OTHER = 170.0

# Minimum returned BMR to avoid unrealistic values for edge-case inputs.
MIN_BMR_KCAL = 800.0


@dataclass
class BmrEstimate:
    bmr: float
    explanation: str
    ai_estimated: bool = False


def typical_height_cm(gender: str | None) -> float:
    """Return a typical standing height in centimeters for the given gender.

    Args:
        gender: Profile gender string (`"male"`, `"female"`, or other/None).

    Returns:
        Assumed height in cm used when the profile has no recorded height.
    """
    if gender == "female":
        return DEFAULT_HEIGHT_CM["female"]
    if gender == "male":
        return DEFAULT_HEIGHT_CM["male"]
    return DEFAULT_HEIGHT_CM_OTHER


def resolve_height_cm(user: User) -> float:
    """Return profile height or a gender-based typical height fallback."""
    return profile_height_cm(user) or typical_height_cm(user.gender)


def calculate_bmr_mifflin_st_jeor(
    weight_kg: float,
    age: int,
    *,
    gender: str | None = None,
    height_cm: float | None = None,
) -> float:
    """Calculate daily BMR (kcal) using the Mifflin-St Jeor equation.

    Formulas (W = weight kg, H = height cm, A = age years):

    - Female: ``10*W + 6.25*H - 5*A - 161``
    - Male / other: ``10*W + 6.25*H - 5*A + 5``

    Args:
        weight_kg: Body weight in kilograms.
        age: Age in whole years.
        gender: When ``"female"``, the female equation is used; otherwise the
            male/other equation is used.
        height_cm: Optional height override. When omitted, a typical height for
            ``gender`` is assumed via :func:`typical_height_cm`.

    Returns:
        Estimated basal metabolic rate in kcal/day, rounded to one decimal and
        floored at :data:`MIN_BMR_KCAL`.
    """
    height = height_cm if height_cm is not None else typical_height_cm(gender)

    if gender == "female":
        bmr = 10 * weight_kg + 6.25 * height - 5 * age - 161
    else:
        bmr = 10 * weight_kg + 6.25 * height - 5 * age + 5

    return round(max(bmr, MIN_BMR_KCAL), 1)


def _profile_ready(user: User) -> bool:
    return user.birth_date is not None and user.weight_kg is not None


def _format_gender_label(gender: str | None) -> str:
    labels = {"male": "male", "female": "female", "other": "other"}
    return labels.get(gender or "", "unspecified")


def _build_bmr_explanation(user: User, height_cm: float, age: int, bmr: float) -> str:
    height_text = f"{int(round(height_cm))} cm"
    if profile_height_cm(user) is None:
        height_text = (
            f"{int(round(height_cm))} cm (typical estimate — add height to your profile for a precise BMR)"
        )

    return (
        f"BMR {bmr:g} kcal/day is the energy your body burns at rest. "
        "Calculated locally with the Mifflin-St Jeor formula using your profile: "
        f"{user.weight_kg:g} kg, age {age}, height {height_text}, gender {_format_gender_label(user.gender)}. "
        "No AI was used."
    )


def calculate_user_bmr(user: User) -> BmrEstimate | None:
    """Calculate BMR for a user profile using local data only.

    Requires ``user.birth_date`` and ``user.weight_kg``. No external AI calls are made.

    Args:
        user: Profile with birth date, weight, and optional gender/height.

    Returns:
        :class:`BmrEstimate` when the profile has enough data, otherwise ``None``.
    """
    if not _profile_ready(user):
        return None

    age = user_age_for_calculations(user)
    if age is None:
        return None

    height_cm = resolve_height_cm(user)
    bmr = calculate_bmr_mifflin_st_jeor(
        float(user.weight_kg),
        age,
        gender=user.gender,
        height_cm=height_cm,
    )
    return BmrEstimate(
        bmr=bmr,
        explanation=_build_bmr_explanation(user, height_cm, age, bmr),
        ai_estimated=False,
    )


def apply_bmr_to_user(user: User) -> bool:
    """Recalculate BMR from the user's profile and write it onto ``user``.

    Clears ``user.bmr`` and ``user.bmr_explanation`` when birth date or weight is missing.

    Args:
        user: User model instance to update in place.

    Returns:
        ``True`` if BMR was calculated and set, ``False`` if profile data is incomplete.
    """
    estimate = calculate_user_bmr(user)
    if estimate is None:
        user.bmr = None
        user.bmr_explanation = None
        return False

    user.bmr = estimate.bmr
    user.bmr_explanation = estimate.explanation
    return True


def recalculate_all_users_bmr(db: Session) -> None:
    """Recalculate and persist BMR for every user with a complete profile."""
    users = db.query(User).all()
    if not users:
        return

    for user in users:
        apply_bmr_to_user(user)
    db.commit()
