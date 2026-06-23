import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy.orm import Session

from bmr_calculator import apply_bmr_to_user
from models import DailySteps, DailyWeight, Meal, User, Workout

EXPORT_VERSION = 1
ImportMode = Literal["overwrite", "new_only"]
ConflictChoice = Literal["existing", "imported"]

CSV_COLUMNS = [
    "record_type",
    "logged_at",
    "entry_date",
    "food_name",
    "activity_type",
    "calories",
    "protein",
    "carbohydrates",
    "fats",
    "calories_burned",
    "steps_count",
    "weight_kg",
    "ai_explanation",
    "name",
    "email",
    "gender",
    "birth_date",
    "height_cm",
    "profile_weight_kg",
    "initial_weight_kg",
]


@dataclass
class ImportResult:
    profile_updated: bool
    meals_imported: int
    workouts_imported: int
    steps_upserted: int
    weights_upserted: int
    meals_skipped: int = 0
    workouts_skipped: int = 0
    steps_skipped: int = 0
    weights_skipped: int = 0

    def to_dict(self) -> dict:
        return {
            "profile_updated": self.profile_updated,
            "meals_imported": self.meals_imported,
            "workouts_imported": self.workouts_imported,
            "steps_upserted": self.steps_upserted,
            "weights_upserted": self.weights_upserted,
            "meals_skipped": self.meals_skipped,
            "workouts_skipped": self.workouts_skipped,
            "steps_skipped": self.steps_skipped,
            "weights_skipped": self.weights_skipped,
        }


def _profile_dict(user: User) -> dict:
    return {
        "name": user.name,
        "email": user.email,
        "gender": user.gender,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "height_cm": user.height_cm,
        "weight_kg": user.weight_kg,
        "initial_weight_kg": user.initial_weight_kg,
    }


def build_export_payload(user: User, db: Session) -> dict:
    meals = (
        db.query(Meal)
        .filter(Meal.user_id == user.id)
        .order_by(Meal.logged_at.asc())
        .all()
    )
    workouts = (
        db.query(Workout)
        .filter(Workout.user_id == user.id)
        .order_by(Workout.logged_at.asc())
        .all()
    )
    steps = (
        db.query(DailySteps)
        .filter(DailySteps.user_id == user.id)
        .order_by(DailySteps.entry_date.asc())
        .all()
    )
    weights = (
        db.query(DailyWeight)
        .filter(DailyWeight.user_id == user.id)
        .order_by(DailyWeight.entry_date.asc())
        .all()
    )

    return {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "username": user.username,
        "profile": _profile_dict(user),
        "meals": [
            {
                "food_name": meal.food_name,
                "calories": meal.calories,
                "protein": meal.protein,
                "carbohydrates": meal.carbohydrates,
                "fats": meal.fats,
                "logged_at": meal.logged_at.isoformat(),
            }
            for meal in meals
        ],
        "workouts": [
            {
                "activity_type": workout.activity_type,
                "calories_burned": workout.calories_burned,
                "logged_at": workout.logged_at.isoformat(),
            }
            for workout in workouts
        ],
        "daily_steps": [
            {
                "entry_date": record.entry_date.isoformat(),
                "steps_count": record.steps_count,
                "calories_burned": record.calories_burned,
                "ai_explanation": record.ai_explanation,
            }
            for record in steps
        ],
        "daily_weights": [
            {
                "entry_date": record.entry_date.isoformat(),
                "weight_kg": record.weight_kg,
            }
            for record in weights
        ],
    }


def export_json(user: User, db: Session) -> str:
    return json.dumps(build_export_payload(user, db), ensure_ascii=False, indent=2)


def export_csv(user: User, db: Session) -> str:
    payload = build_export_payload(user, db)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    profile = payload["profile"]
    writer.writerow(
        {
            "record_type": "profile",
            "name": profile.get("name"),
            "email": profile.get("email"),
            "gender": profile.get("gender"),
            "birth_date": profile.get("birth_date"),
            "height_cm": profile.get("height_cm"),
            "profile_weight_kg": profile.get("weight_kg"),
            "initial_weight_kg": profile.get("initial_weight_kg"),
        }
    )

    for meal in payload["meals"]:
        writer.writerow(
            {
                "record_type": "meal",
                "logged_at": meal.get("logged_at"),
                "food_name": meal.get("food_name"),
                "calories": meal.get("calories"),
                "protein": meal.get("protein"),
                "carbohydrates": meal.get("carbohydrates"),
                "fats": meal.get("fats"),
            }
        )

    for workout in payload["workouts"]:
        writer.writerow(
            {
                "record_type": "workout",
                "logged_at": workout.get("logged_at"),
                "activity_type": workout.get("activity_type"),
                "calories_burned": workout.get("calories_burned"),
            }
        )

    for record in payload["daily_steps"]:
        writer.writerow(
            {
                "record_type": "steps",
                "entry_date": record.get("entry_date"),
                "steps_count": record.get("steps_count"),
                "calories_burned": record.get("calories_burned"),
                "ai_explanation": record.get("ai_explanation"),
            }
        )

    for record in payload["daily_weights"]:
        writer.writerow(
            {
                "record_type": "weight",
                "entry_date": record.get("entry_date"),
                "weight_kg": record.get("weight_kg"),
            }
        )

    return buffer.getvalue()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value).strip())


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    return datetime.fromisoformat(text)


def _parse_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _timestamp_key(value: str | datetime) -> str:
    dt = _parse_datetime(value) if isinstance(value, str) else value
    return dt.replace(microsecond=0).isoformat()


def _date_key(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _floats_equal(left, right, tolerance: float = 0.01) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= tolerance


def _meal_dict(item: dict) -> dict | None:
    if not item.get("food_name"):
        return None
    return {
        "food_name": str(item["food_name"]).strip(),
        "calories": float(item.get("calories") or 0),
        "protein": float(item.get("protein") or 0),
        "carbohydrates": float(item.get("carbohydrates") or 0),
        "fats": float(item.get("fats") or 0),
        "logged_at": _timestamp_key(item.get("logged_at")),
    }


def _workout_dict(item: dict) -> dict | None:
    if not item.get("activity_type"):
        return None
    return {
        "activity_type": str(item["activity_type"]).strip(),
        "calories_burned": float(item.get("calories_burned") or 0),
        "logged_at": _timestamp_key(item.get("logged_at")),
    }


def _steps_dict(item: dict) -> dict | None:
    entry_date = _parse_date(item.get("entry_date"))
    steps_count = _parse_int(item.get("steps_count"))
    if entry_date is None or steps_count is None:
        return None
    return {
        "entry_date": entry_date.isoformat(),
        "steps_count": steps_count,
        "calories_burned": float(item.get("calories_burned") or 0),
        "ai_explanation": item.get("ai_explanation"),
    }


def _weight_dict(item: dict) -> dict | None:
    entry_date = _parse_date(item.get("entry_date"))
    weight_kg = _parse_float(item.get("weight_kg"))
    if entry_date is None or weight_kg is None:
        return None
    return {
        "entry_date": entry_date.isoformat(),
        "weight_kg": weight_kg,
    }


def _meals_equal(existing: dict, imported: dict) -> bool:
    return (
        existing["food_name"] == imported["food_name"]
        and _floats_equal(existing["calories"], imported["calories"])
        and _floats_equal(existing["protein"], imported["protein"])
        and _floats_equal(existing["carbohydrates"], imported["carbohydrates"])
        and _floats_equal(existing["fats"], imported["fats"])
    )


def _workouts_equal(existing: dict, imported: dict) -> bool:
    return existing["activity_type"] == imported["activity_type"] and _floats_equal(
        existing["calories_burned"], imported["calories_burned"]
    )


def _steps_equal(existing: dict, imported: dict) -> bool:
    return (
        existing["steps_count"] == imported["steps_count"]
        and _floats_equal(existing["calories_burned"], imported["calories_burned"])
        and (existing.get("ai_explanation") or "") == (imported.get("ai_explanation") or "")
    )


def _weights_equal(existing: dict, imported: dict) -> bool:
    return _floats_equal(existing["weight_kg"], imported["weight_kg"])


def _profile_has_importable_data(profile: dict) -> bool:
    if not profile:
        return False
    return any(
        profile.get(field) not in (None, "")
        for field in (
            "name",
            "email",
            "gender",
            "birth_date",
            "height_cm",
            "weight_kg",
            "initial_weight_kg",
        )
    )


def _profile_differs(user: User, profile: dict) -> bool:
    if not _profile_has_importable_data(profile):
        return False

    comparisons = [
        (user.name, profile.get("name")),
        (user.email, profile.get("email")),
        (user.gender, profile.get("gender")),
        (
            user.birth_date.isoformat() if user.birth_date else None,
            profile.get("birth_date"),
        ),
        (user.height_cm, profile.get("height_cm")),
        (user.weight_kg, profile.get("weight_kg")),
        (user.initial_weight_kg, profile.get("initial_weight_kg")),
    ]
    for existing_value, imported_value in comparisons:
        if imported_value in (None, ""):
            continue
        if _values_differ(existing_value, imported_value):
            return True
    return False


def _values_differ(existing, imported) -> bool:
    if isinstance(existing, float) or isinstance(imported, float):
        return not _floats_equal(existing, imported)
    existing_text = str(existing).strip().lower() if existing is not None else ""
    imported_text = str(imported).strip().lower() if imported is not None else ""
    return existing_text != imported_text


def parse_json_payload(raw: dict) -> dict:
    version = raw.get("export_version")
    if version != EXPORT_VERSION:
        raise ValueError(f"Unsupported export version: {version}")
    return raw


def parse_csv_payload(content: str) -> dict:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or "record_type" not in reader.fieldnames:
        raise ValueError("CSV must include a record_type column")

    profile: dict = {}
    meals: list[dict] = []
    workouts: list[dict] = []
    daily_steps: list[dict] = []
    daily_weights: list[dict] = []

    for row in reader:
        record_type = (row.get("record_type") or "").strip().lower()
        if record_type == "profile":
            profile = {
                "name": row.get("name"),
                "email": row.get("email"),
                "gender": row.get("gender"),
                "birth_date": row.get("birth_date"),
                "height_cm": row.get("height_cm"),
                "weight_kg": row.get("profile_weight_kg"),
                "initial_weight_kg": row.get("initial_weight_kg"),
            }
        elif record_type == "meal":
            meals.append(row)
        elif record_type == "workout":
            workouts.append(row)
        elif record_type == "steps":
            daily_steps.append(
                {
                    "entry_date": row.get("entry_date"),
                    "steps_count": row.get("steps_count"),
                    "calories_burned": row.get("calories_burned"),
                    "ai_explanation": row.get("ai_explanation"),
                }
            )
        elif record_type == "weight":
            daily_weights.append(
                {
                    "entry_date": row.get("entry_date"),
                    "weight_kg": row.get("weight_kg"),
                }
            )

    return {
        "export_version": EXPORT_VERSION,
        "profile": profile,
        "meals": [
            {
                "food_name": row.get("food_name"),
                "calories": row.get("calories"),
                "protein": row.get("protein"),
                "carbohydrates": row.get("carbohydrates"),
                "fats": row.get("fats"),
                "logged_at": row.get("logged_at"),
            }
            for row in meals
        ],
        "workouts": [
            {
                "activity_type": row.get("activity_type"),
                "calories_burned": row.get("calories_burned"),
                "logged_at": row.get("logged_at"),
            }
            for row in workouts
        ],
        "daily_steps": daily_steps,
        "daily_weights": daily_weights,
    }


def _existing_meals(user: User, db: Session) -> dict[str, dict]:
    records = {}
    for meal in db.query(Meal).filter(Meal.user_id == user.id).all():
        records[_timestamp_key(meal.logged_at)] = {
            "id": meal.id,
            "food_name": meal.food_name,
            "calories": meal.calories,
            "protein": meal.protein,
            "carbohydrates": meal.carbohydrates,
            "fats": meal.fats,
            "logged_at": _timestamp_key(meal.logged_at),
        }
    return records


def _existing_workouts(user: User, db: Session) -> dict[str, dict]:
    records = {}
    for workout in db.query(Workout).filter(Workout.user_id == user.id).all():
        records[_timestamp_key(workout.logged_at)] = {
            "id": workout.id,
            "activity_type": workout.activity_type,
            "calories_burned": workout.calories_burned,
            "logged_at": _timestamp_key(workout.logged_at),
        }
    return records


def _existing_steps(user: User, db: Session) -> dict[str, dict]:
    records = {}
    for record in db.query(DailySteps).filter(DailySteps.user_id == user.id).all():
        records[record.entry_date.isoformat()] = {
            "entry_date": record.entry_date.isoformat(),
            "steps_count": record.steps_count,
            "calories_burned": record.calories_burned,
            "ai_explanation": record.ai_explanation,
        }
    return records


def _existing_weights(user: User, db: Session) -> dict[str, dict]:
    records = {}
    for record in db.query(DailyWeight).filter(DailyWeight.user_id == user.id).all():
        records[record.entry_date.isoformat()] = {
            "entry_date": record.entry_date.isoformat(),
            "weight_kg": record.weight_kg,
        }
    return records


def preview_import(user: User, db: Session, payload: dict) -> dict:
    existing_meals = _existing_meals(user, db)
    existing_workouts = _existing_workouts(user, db)
    existing_steps = _existing_steps(user, db)
    existing_weights = _existing_weights(user, db)

    summary = {
        "meals_new": 0,
        "meals_duplicate": 0,
        "meals_conflict": 0,
        "workouts_new": 0,
        "workouts_duplicate": 0,
        "workouts_conflict": 0,
        "steps_new": 0,
        "steps_duplicate": 0,
        "steps_conflict": 0,
        "weights_new": 0,
        "weights_duplicate": 0,
        "weights_conflict": 0,
    }
    conflicts = {"meals": [], "workouts": [], "steps": [], "weights": []}

    for item in payload.get("meals") or []:
        imported = _meal_dict(item)
        if imported is None:
            continue
        key = imported["logged_at"]
        existing = existing_meals.get(key)
        if existing is None:
            summary["meals_new"] += 1
        elif _meals_equal(existing, imported):
            summary["meals_duplicate"] += 1
        else:
            summary["meals_conflict"] += 1
            conflicts["meals"].append({"key": key, "existing": existing, "imported": imported})

    for item in payload.get("workouts") or []:
        imported = _workout_dict(item)
        if imported is None:
            continue
        key = imported["logged_at"]
        existing = existing_workouts.get(key)
        if existing is None:
            summary["workouts_new"] += 1
        elif _workouts_equal(existing, imported):
            summary["workouts_duplicate"] += 1
        else:
            summary["workouts_conflict"] += 1
            conflicts["workouts"].append({"key": key, "existing": existing, "imported": imported})

    for item in payload.get("daily_steps") or []:
        imported = _steps_dict(item)
        if imported is None:
            continue
        key = imported["entry_date"]
        existing = existing_steps.get(key)
        if existing is None:
            summary["steps_new"] += 1
        elif _steps_equal(existing, imported):
            summary["steps_duplicate"] += 1
        else:
            summary["steps_conflict"] += 1
            conflicts["steps"].append({"key": key, "existing": existing, "imported": imported})

    for item in payload.get("daily_weights") or []:
        imported = _weight_dict(item)
        if imported is None:
            continue
        key = imported["entry_date"]
        existing = existing_weights.get(key)
        if existing is None:
            summary["weights_new"] += 1
        elif _weights_equal(existing, imported):
            summary["weights_duplicate"] += 1
        else:
            summary["weights_conflict"] += 1
            conflicts["weights"].append({"key": key, "existing": existing, "imported": imported})

    profile = payload.get("profile") or {}
    profile_conflict = _profile_differs(user, profile)
    total_conflicts = (
        summary["meals_conflict"]
        + summary["workouts_conflict"]
        + summary["steps_conflict"]
        + summary["weights_conflict"]
        + (1 if profile_conflict else 0)
    )

    return {
        "summary": summary,
        "conflicts": conflicts,
        "profile": {
            "has_conflict": profile_conflict,
            "existing": _profile_dict(user),
            "imported": profile if _profile_has_importable_data(profile) else None,
        },
        "has_conflicts": total_conflicts > 0,
    }


def _apply_profile(user: User, db: Session, profile: dict) -> bool:
    if not profile:
        return False

    updated = False
    if profile.get("name"):
        user.name = str(profile["name"]).strip()
        updated = True
    if "email" in profile:
        email = str(profile["email"]).lower() if profile["email"] else None
        if email:
            existing = db.query(User).filter(User.email == email, User.id != user.id).first()
            if existing:
                raise ValueError("Email already registered")
        user.email = email
        updated = True
    if "gender" in profile:
        user.gender = profile["gender"] or None
        updated = True
    if profile.get("birth_date"):
        user.birth_date = _parse_date(profile["birth_date"])
        updated = True
    if profile.get("height_cm") is not None:
        user.height_cm = _parse_float(profile["height_cm"])
        updated = True
    if profile.get("weight_kg") is not None:
        user.weight_kg = _parse_float(profile["weight_kg"])
        updated = True
    if profile.get("initial_weight_kg") is not None:
        user.initial_weight_kg = _parse_float(profile["initial_weight_kg"])
        updated = True

    if updated:
        apply_bmr_to_user(user)
    return updated


def _normalize_resolutions(resolutions: dict | None) -> dict:
    resolutions = resolutions or {}
    return {
        "profile": resolutions.get("profile"),
        "meals": resolutions.get("meals") or {},
        "workouts": resolutions.get("workouts") or {},
        "steps": resolutions.get("steps") or {},
        "weights": resolutions.get("weights") or {},
    }


def _choice_for(
    resolutions: dict,
    category: str,
    key: str,
    mode: ImportMode,
) -> ConflictChoice:
    if mode == "overwrite":
        return "imported"
    choice = resolutions[category].get(key)
    if choice in ("existing", "imported"):
        return choice
    return "existing"


def _update_meal(record: Meal, imported: dict) -> None:
    record.food_name = imported["food_name"]
    record.calories = imported["calories"]
    record.protein = imported["protein"]
    record.carbohydrates = imported["carbohydrates"]
    record.fats = imported["fats"]


def _update_workout(record: Workout, imported: dict) -> None:
    record.activity_type = imported["activity_type"]
    record.calories_burned = imported["calories_burned"]


def _update_steps(record: DailySteps, imported: dict) -> None:
    record.steps_count = imported["steps_count"]
    record.calories_burned = imported["calories_burned"]
    record.ai_explanation = imported.get("ai_explanation")
    record.updated_at = datetime.utcnow()


def _update_weight(record: DailyWeight, imported: dict) -> None:
    record.weight_kg = imported["weight_kg"]
    record.updated_at = datetime.utcnow()


def _clear_user_tracking_data(user: User, db: Session) -> None:
    db.query(Meal).filter(Meal.user_id == user.id).delete(synchronize_session=False)
    db.query(Workout).filter(Workout.user_id == user.id).delete(synchronize_session=False)
    db.query(DailySteps).filter(DailySteps.user_id == user.id).delete(synchronize_session=False)
    db.query(DailyWeight).filter(DailyWeight.user_id == user.id).delete(synchronize_session=False)


def _insert_payload_records(user: User, db: Session, payload: dict) -> ImportResult:
    profile_updated = False
    profile = payload.get("profile") or {}
    if _profile_has_importable_data(profile):
        profile_updated = _apply_profile(user, db, profile)

    meals_imported = 0
    for item in payload.get("meals") or []:
        imported = _meal_dict(item)
        if imported is None:
            continue
        db.add(
            Meal(
                user_id=user.id,
                food_name=imported["food_name"],
                calories=imported["calories"],
                protein=imported["protein"],
                carbohydrates=imported["carbohydrates"],
                fats=imported["fats"],
                logged_at=_parse_datetime(imported["logged_at"]),
            )
        )
        meals_imported += 1

    workouts_imported = 0
    for item in payload.get("workouts") or []:
        imported = _workout_dict(item)
        if imported is None:
            continue
        db.add(
            Workout(
                user_id=user.id,
                activity_type=imported["activity_type"],
                calories_burned=imported["calories_burned"],
                logged_at=_parse_datetime(imported["logged_at"]),
            )
        )
        workouts_imported += 1

    steps_upserted = 0
    for item in payload.get("daily_steps") or []:
        imported = _steps_dict(item)
        if imported is None:
            continue
        db.add(
            DailySteps(
                user_id=user.id,
                entry_date=_parse_date(imported["entry_date"]),
                steps_count=imported["steps_count"],
                calories_burned=imported["calories_burned"],
                ai_explanation=imported.get("ai_explanation"),
            )
        )
        steps_upserted += 1

    weights_upserted = 0
    for item in payload.get("daily_weights") or []:
        imported = _weight_dict(item)
        if imported is None:
            continue
        db.add(
            DailyWeight(
                user_id=user.id,
                entry_date=_parse_date(imported["entry_date"]),
                weight_kg=imported["weight_kg"],
            )
        )
        weights_upserted += 1

    return ImportResult(
        profile_updated=profile_updated,
        meals_imported=meals_imported,
        workouts_imported=workouts_imported,
        steps_upserted=steps_upserted,
        weights_upserted=weights_upserted,
    )


def _apply_merge_import(
    user: User,
    db: Session,
    payload: dict,
    resolutions: dict,
    preview: dict,
) -> ImportResult:
    profile_updated = False
    profile = payload.get("profile") or {}
    if preview["profile"]["has_conflict"]:
        if resolutions["profile"] == "imported":
            profile_updated = _apply_profile(user, db, profile)
    elif _profile_has_importable_data(profile) and not preview["profile"]["has_conflict"]:
        profile_updated = _apply_profile(user, db, profile)

    existing_meal_rows = db.query(Meal).filter(Meal.user_id == user.id).all()
    existing_workout_rows = db.query(Workout).filter(Workout.user_id == user.id).all()
    existing_step_rows = db.query(DailySteps).filter(DailySteps.user_id == user.id).all()
    existing_weight_rows = db.query(DailyWeight).filter(DailyWeight.user_id == user.id).all()

    existing_meal_data = {
        _timestamp_key(meal.logged_at): {
            "id": meal.id,
            "food_name": meal.food_name,
            "calories": meal.calories,
            "protein": meal.protein,
            "carbohydrates": meal.carbohydrates,
            "fats": meal.fats,
            "logged_at": _timestamp_key(meal.logged_at),
        }
        for meal in existing_meal_rows
    }
    existing_meals = {_timestamp_key(meal.logged_at): meal for meal in existing_meal_rows}
    existing_workout_data = {
        _timestamp_key(workout.logged_at): {
            "id": workout.id,
            "activity_type": workout.activity_type,
            "calories_burned": workout.calories_burned,
            "logged_at": _timestamp_key(workout.logged_at),
        }
        for workout in existing_workout_rows
    }
    existing_workouts = {_timestamp_key(workout.logged_at): workout for workout in existing_workout_rows}
    existing_step_data = {
        record.entry_date.isoformat(): {
            "entry_date": record.entry_date.isoformat(),
            "steps_count": record.steps_count,
            "calories_burned": record.calories_burned,
            "ai_explanation": record.ai_explanation,
        }
        for record in existing_step_rows
    }
    existing_steps = {record.entry_date.isoformat(): record for record in existing_step_rows}
    existing_weight_data = {
        record.entry_date.isoformat(): {
            "entry_date": record.entry_date.isoformat(),
            "weight_kg": record.weight_kg,
        }
        for record in existing_weight_rows
    }
    existing_weights = {record.entry_date.isoformat(): record for record in existing_weight_rows}

    meals_imported = 0
    meals_skipped = 0
    for item in payload.get("meals") or []:
        imported = _meal_dict(item)
        if imported is None:
            continue
        key = imported["logged_at"]
        existing = existing_meals.get(key)
        if existing is None:
            db.add(
                Meal(
                    user_id=user.id,
                    food_name=imported["food_name"],
                    calories=imported["calories"],
                    protein=imported["protein"],
                    carbohydrates=imported["carbohydrates"],
                    fats=imported["fats"],
                    logged_at=_parse_datetime(imported["logged_at"]),
                )
            )
            meals_imported += 1
            continue

        existing_data = existing_meal_data.get(key)
        if existing_data and _meals_equal(existing_data, imported):
            meals_skipped += 1
            continue

        choice = _choice_for(resolutions, "meals", key, "new_only")
        if choice == "imported":
            _update_meal(existing, imported)
            meals_imported += 1
        else:
            meals_skipped += 1

    workouts_imported = 0
    workouts_skipped = 0
    for item in payload.get("workouts") or []:
        imported = _workout_dict(item)
        if imported is None:
            continue
        key = imported["logged_at"]
        existing = existing_workouts.get(key)
        if existing is None:
            db.add(
                Workout(
                    user_id=user.id,
                    activity_type=imported["activity_type"],
                    calories_burned=imported["calories_burned"],
                    logged_at=_parse_datetime(imported["logged_at"]),
                )
            )
            workouts_imported += 1
            continue

        existing_data = existing_workout_data.get(key)
        if existing_data and _workouts_equal(existing_data, imported):
            workouts_skipped += 1
            continue

        choice = _choice_for(resolutions, "workouts", key, "new_only")
        if choice == "imported":
            _update_workout(existing, imported)
            workouts_imported += 1
        else:
            workouts_skipped += 1

    steps_upserted = 0
    steps_skipped = 0
    for item in payload.get("daily_steps") or []:
        imported = _steps_dict(item)
        if imported is None:
            continue
        key = imported["entry_date"]
        existing = existing_steps.get(key)
        if existing is None:
            db.add(
                DailySteps(
                    user_id=user.id,
                    entry_date=_parse_date(key),
                    steps_count=imported["steps_count"],
                    calories_burned=imported["calories_burned"],
                    ai_explanation=imported.get("ai_explanation"),
                )
            )
            steps_upserted += 1
            continue

        existing_data = existing_step_data.get(key)
        if existing_data and _steps_equal(existing_data, imported):
            steps_skipped += 1
            continue

        choice = _choice_for(resolutions, "steps", key, "new_only")
        if choice == "imported":
            _update_steps(existing, imported)
            steps_upserted += 1
        else:
            steps_skipped += 1

    weights_upserted = 0
    weights_skipped = 0
    for item in payload.get("daily_weights") or []:
        imported = _weight_dict(item)
        if imported is None:
            continue
        key = imported["entry_date"]
        existing = existing_weights.get(key)
        if existing is None:
            db.add(
                DailyWeight(
                    user_id=user.id,
                    entry_date=_parse_date(key),
                    weight_kg=imported["weight_kg"],
                )
            )
            weights_upserted += 1
            continue

        existing_data = existing_weight_data.get(key)
        if existing_data and _weights_equal(existing_data, imported):
            weights_skipped += 1
            continue

        choice = _choice_for(resolutions, "weights", key, "new_only")
        if choice == "imported":
            _update_weight(existing, imported)
            weights_upserted += 1
        else:
            weights_skipped += 1

    return ImportResult(
        profile_updated=profile_updated,
        meals_imported=meals_imported,
        workouts_imported=workouts_imported,
        steps_upserted=steps_upserted,
        weights_upserted=weights_upserted,
        meals_skipped=meals_skipped,
        workouts_skipped=workouts_skipped,
        steps_skipped=steps_skipped,
        weights_skipped=weights_skipped,
    )


def apply_import(
    user: User,
    db: Session,
    payload: dict,
    mode: ImportMode,
    resolutions: dict | None = None,
) -> ImportResult:
    resolutions = _normalize_resolutions(resolutions)
    if mode == "overwrite":
        _clear_user_tracking_data(user, db)
        return _insert_payload_records(user, db, payload)

    preview = preview_import(user, db, payload)
    return _apply_merge_import(user, db, payload, resolutions, preview)


def import_json_payload(
    user: User,
    db: Session,
    payload: dict,
    mode: ImportMode = "overwrite",
    resolutions: dict | None = None,
) -> ImportResult:
    parse_json_payload(payload)
    return apply_import(user, db, payload, mode, resolutions)


def import_csv_payload(
    user: User,
    db: Session,
    content: str,
    mode: ImportMode = "overwrite",
    resolutions: dict | None = None,
) -> ImportResult:
    payload = parse_csv_payload(content)
    return apply_import(user, db, payload, mode, resolutions)
