from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import DailySteps, DailyWeight, Meal, User, Workout

PERIOD_RANGES = frozenset({"5d", "7d", "30d", "365d", "all"})


def macros_goal_from_bmr(bmr: float | None) -> dict | None:
    if bmr is None:
        return None
    return {
        "protein_g": round(bmr * 0.25 / 4, 1),
        "carbohydrates_g": round(bmr * 0.45 / 4, 1),
        "fats_g": round(bmr * 0.30 / 9, 1),
    }


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(target_date, time.min), datetime.combine(target_date, time.max)


def earliest_data_date(db: Session, user_id: int) -> date | None:
    candidates: list[date] = []

    meal_min = (
        db.query(func.min(Meal.logged_at))
        .filter(Meal.user_id == user_id)
        .scalar()
    )
    if meal_min is not None:
        candidates.append(meal_min.date())

    workout_min = (
        db.query(func.min(Workout.logged_at))
        .filter(Workout.user_id == user_id)
        .scalar()
    )
    if workout_min is not None:
        candidates.append(workout_min.date())

    steps_min = (
        db.query(func.min(DailySteps.entry_date))
        .filter(DailySteps.user_id == user_id)
        .scalar()
    )
    if steps_min is not None:
        candidates.append(steps_min)

    weight_min = (
        db.query(func.min(DailyWeight.entry_date))
        .filter(DailyWeight.user_id == user_id)
        .scalar()
    )
    if weight_min is not None:
        candidates.append(weight_min)

    return min(candidates) if candidates else None


def resolve_period(range_key: str, end_date: date, earliest: date | None) -> tuple[date, date]:
    if range_key == "5d":
        return end_date - timedelta(days=4), end_date
    if range_key == "7d":
        return end_date - timedelta(days=6), end_date
    if range_key == "30d":
        return end_date - timedelta(days=29), end_date
    if range_key == "365d":
        return end_date - timedelta(days=364), end_date
    return earliest or end_date, end_date


def _build_day_metrics(db: Session, user: User, target_date: date) -> dict:
    day_start, day_end = _day_bounds(target_date)
    bmr = float(user.bmr) if user.bmr is not None else None

    calories_consumed = float(
        db.query(func.coalesce(func.sum(Meal.calories), 0.0))
        .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
        .scalar()
    )
    total_protein = float(
        db.query(func.coalesce(func.sum(Meal.protein), 0.0))
        .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
        .scalar()
    )
    total_carbohydrates = float(
        db.query(func.coalesce(func.sum(Meal.carbohydrates), 0.0))
        .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
        .scalar()
    )
    total_fats = float(
        db.query(func.coalesce(func.sum(Meal.fats), 0.0))
        .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
        .scalar()
    )
    workout_calories_burned = float(
        db.query(func.coalesce(func.sum(Workout.calories_burned), 0.0))
        .filter(Workout.user_id == user.id, Workout.logged_at >= day_start, Workout.logged_at <= day_end)
        .scalar()
    )

    steps_record = (
        db.query(DailySteps)
        .filter(DailySteps.user_id == user.id, DailySteps.entry_date == target_date)
        .first()
    )
    weight_record = (
        db.query(DailyWeight)
        .filter(DailyWeight.user_id == user.id, DailyWeight.entry_date == target_date)
        .first()
    )

    steps_calories_burned = float(steps_record.calories_burned) if steps_record else 0.0
    activity_calories_burned = workout_calories_burned + steps_calories_burned
    total_calories_out = (bmr + activity_calories_burned) if bmr is not None else activity_calories_burned

    return {
        "date": target_date.isoformat(),
        "calories_consumed": calories_consumed,
        "calories_burned": total_calories_out,
        "activity_calories_burned": activity_calories_burned,
        "workout_calories_burned": workout_calories_burned,
        "steps_calories_burned": steps_calories_burned,
        "total_protein": total_protein,
        "total_carbohydrates": total_carbohydrates,
        "total_fats": total_fats,
        "steps_count": steps_record.steps_count if steps_record else None,
        "weight_kg": weight_record.weight_kg if weight_record else None,
    }


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def build_period_summary(
    db: Session,
    user: User,
    range_key: str,
    end_date: date | None = None,
) -> dict:
    end_date = end_date or date.today()
    earliest = earliest_data_date(db, user.id)
    start_date, resolved_end = resolve_period(range_key, end_date, earliest)

    days: list[dict] = []
    cursor = start_date
    while cursor <= resolved_end:
        days.append(_build_day_metrics(db, user, cursor))
        cursor += timedelta(days=1)

    consumed_values = [day["calories_consumed"] for day in days]
    burned_values = [day["calories_burned"] for day in days]
    protein_values = [day["total_protein"] for day in days]
    carbs_values = [day["total_carbohydrates"] for day in days]
    fats_values = [day["total_fats"] for day in days]
    steps_values = [day["steps_count"] for day in days if day["steps_count"] is not None]
    weight_values = [day["weight_kg"] for day in days if day["weight_kg"] is not None]

    bmr = float(user.bmr) if user.bmr is not None else None

    return {
        "range": range_key,
        "start_date": start_date.isoformat(),
        "end_date": resolved_end.isoformat(),
        "bmr": bmr,
        "macro_goals": macros_goal_from_bmr(bmr),
        "days": days,
        "averages": {
            "calories_consumed": _average(consumed_values),
            "calories_burned": _average(burned_values),
            "total_protein": _average(protein_values),
            "total_carbohydrates": _average(carbs_values),
            "total_fats": _average(fats_values),
            "steps_count": _average([float(value) for value in steps_values]),
            "weight_kg": _average(weight_values),
        },
    }
