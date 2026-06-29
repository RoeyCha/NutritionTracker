import json
import logging
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, time as dt_time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from app_logging import setup_logging

setup_logging()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gemini_daily_tips import get_or_create_daily_tips
from gemini_insight import generate_daily_insight
from profile_utils import validate_birth_date
from ai_calories import CalorieEstimate, calories_from_macros, estimate_meal_calories, estimate_workout_calories
from bmr_calculator import apply_bmr_to_user, recalculate_all_users_bmr
from auth import (
    create_access_token,
    get_current_user,
    get_current_user_for_download,
    get_db,
    hash_password,
    user_to_dict,
    verify_password,
)
from models import DailySteps, DailyWeight, Meal, SessionLocal, User, Workout, init_db
from seed import seed_test_user
from steps_calories import estimate_steps_calories
from user_data_io import (
    export_csv,
    export_json,
    import_csv_payload,
    import_json_payload,
    parse_csv_payload,
    parse_json_payload,
    preview_import,
)

logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")


app = FastAPI(title="Nutrition Tracker MVP", default_response_class=UTF8JSONResponse)
templates = Jinja2Templates(directory="templates")

SEO_META = {
    "page_title": "Nutrition Tracker",
    "page_description": (
        "Log meals and workouts, track calories, BMR, and your daily nutrition balance."
    ),
    "og_title": "Nutrition Tracker",
    "og_description": (
        "Log meals and workouts, track calories, BMR, and your daily nutrition balance."
    ),
    "og_type": "website",
}


def _cors_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "%s %s -> unhandled error (%.0f ms)",
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %s (%.0f ms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=4, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr | None = None
    gender: str | None = Field(default=None, pattern=r"^(male|female|other)$")
    birth_date: date | None = None
    height_cm: int | None = Field(default=None, ge=50, le=300)
    weight_kg: float | None = Field(default=None, gt=0, le=500)

    @field_validator("gender", mode="before")
    @classmethod
    def empty_gender_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("height_cm", mode="before")
    @classmethod
    def normalize_height_cm(cls, value):
        if value == "" or value is None:
            return None
        return int(round(float(value)))

    @field_validator("weight_kg", mode="before")
    @classmethod
    def empty_weight_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date_field(cls, value: date | None) -> date | None:
        return validate_birth_date(value)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class ProfileUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr | None = None
    gender: str | None = Field(default=None, pattern=r"^(male|female|other)$")
    birth_date: date | None = None
    height_cm: int | None = Field(default=None, ge=50, le=300)
    weight_kg: float | None = Field(default=None, gt=0, le=500)

    @field_validator("gender", mode="before")
    @classmethod
    def empty_gender_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("height_cm", mode="before")
    @classmethod
    def normalize_height_cm(cls, value):
        if value == "" or value is None:
            return None
        return int(round(float(value)))

    @field_validator("weight_kg", mode="before")
    @classmethod
    def empty_weight_to_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date_field(cls, value: date | None) -> date | None:
        return validate_birth_date(value)


class MealCreate(BaseModel):
    food_name: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None
    protein: float | None = Field(default=None, ge=0)
    carbohydrates: float | None = Field(default=None, ge=0)
    fats: float | None = Field(default=None, ge=0)


class WorkoutCreate(BaseModel):
    activity_type: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None


class MealUpdate(BaseModel):
    food_name: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None
    recalculate_calories: bool = False
    protein: float | None = Field(default=None, ge=0)
    carbohydrates: float | None = Field(default=None, ge=0)
    fats: float | None = Field(default=None, ge=0)


class WorkoutUpdate(BaseModel):
    activity_type: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None
    recalculate_calories: bool = False


class InsightRequest(BaseModel):
    target_date: date | None = Field(default=None, alias="date")
    language: str = Field(default="en", pattern=r"^(en|he)$")

    model_config = {"populate_by_name": True}


class DailyTipsRequest(BaseModel):
    language: str = Field(default="en", pattern=r"^(en|he)$")


class StepsUpsert(BaseModel):
    steps_count: int = Field(..., ge=0, le=100000)


class WeightUpsert(BaseModel):
    weight_kg: float = Field(..., ge=1, le=500)


class ImportResolutions(BaseModel):
    profile: Literal["existing", "imported"] | None = None
    meals: dict[str, Literal["existing", "imported"]] = Field(default_factory=dict)
    workouts: dict[str, Literal["existing", "imported"]] = Field(default_factory=dict)
    steps: dict[str, Literal["existing", "imported"]] = Field(default_factory=dict)
    weights: dict[str, Literal["existing", "imported"]] = Field(default_factory=dict)


class ImportApplyRequest(BaseModel):
    mode: Literal["overwrite", "new_only"] = "overwrite"
    format: Literal["json", "csv"] = "json"
    content: str
    resolutions: ImportResolutions | None = None


def _get_user_meal(meal_id: int, user: User, db: Session) -> Meal:
    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.user_id == user.id).first()
    if meal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found")
    return meal


def _get_user_workout(workout_id: int, user: User, db: Session) -> Workout:
    workout = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == user.id).first()
    if workout is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workout not found")
    return workout


def _normalize_activity_type(activity_type: str) -> str:
    text = unicodedata.normalize("NFKC", activity_type.strip())
    for quote in ('\u05f4', '\u05f3', '\u201c', '\u201d', '\u2018', '\u2019', "'"):
        text = text.replace(quote, '"')
    return " ".join(text.split()).lower()


def _lookup_prior_workout_estimate(
    db: Session,
    user_id: int,
    activity_type: str,
    exclude_workout_id: int | None = None,
) -> CalorieEstimate | None:
    normalized = _normalize_activity_type(activity_type)
    query = (
        db.query(Workout)
        .filter(Workout.user_id == user_id)
        .order_by(Workout.logged_at.desc())
    )
    if exclude_workout_id is not None:
        query = query.filter(Workout.id != exclude_workout_id)

    for prior_workout in query:
        if _normalize_activity_type(prior_workout.activity_type) != normalized:
            continue
        logged_date = prior_workout.logged_at.date().isoformat()
        return CalorieEstimate(
            calories=prior_workout.calories_burned,
            explanation=(
                f'"{prior_workout.activity_type}" was logged before on {logged_date} '
                f"({prior_workout.calories_burned:g} kcal). Reusing that value for consistency — no new estimate."
            ),
            ai_estimated=False,
        )
    return None


def _estimate_workout_calories(
    db: Session,
    user: User,
    activity_type: str,
    *,
    exclude_workout_id: int | None = None,
    allow_reuse: bool = True,
) -> CalorieEstimate:
    if allow_reuse:
        prior = _lookup_prior_workout_estimate(
            db, user.id, activity_type, exclude_workout_id=exclude_workout_id
        )
        if prior is not None:
            logger.info(
                "Reused workout calories for user %s activity %r -> %.1f kcal",
                user.username,
                activity_type,
                prior.calories,
            )
            return prior
    return estimate_workout_calories(activity_type, user)


def _ensure_not_future_logged_at(logged_at: datetime | None) -> datetime:
    resolved = logged_at or datetime.utcnow()
    if resolved.tzinfo is not None:
        resolved = resolved.replace(tzinfo=None)
    if resolved > datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot log meals or workouts in the future",
        )
    return resolved


def _ensure_not_future_date(target_date: date) -> None:
    if target_date > date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot log data for future dates",
        )


def _workouts_for_date(db: Session, user_id: int, target_date: date) -> list[dict]:
    day_start = datetime.combine(target_date, dt_time.min)
    day_end = datetime.combine(target_date, dt_time.max)
    workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == user_id,
            Workout.logged_at >= day_start,
            Workout.logged_at <= day_end,
        )
        .all()
    )
    return [
        {"activity_type": workout.activity_type, "calories_burned": workout.calories_burned}
        for workout in workouts
    ]


def _refresh_daily_steps_calories(db: Session, user: User, target_date: date) -> DailySteps | None:
    record = (
        db.query(DailySteps)
        .filter(DailySteps.user_id == user.id, DailySteps.entry_date == target_date)
        .first()
    )
    if record is None:
        return None

    estimate = estimate_steps_calories(user, record.steps_count, _workouts_for_date(db, user.id, target_date))
    record.calories_burned = estimate.calories_burned
    record.ai_explanation = estimate.explanation
    record.updated_at = datetime.utcnow()
    return record


def _daily_weight_payload(record: DailyWeight | None) -> dict | None:
    if record is None:
        return None
    return {
        "weight_kg": record.weight_kg,
        "updated_at": record.updated_at.isoformat(),
    }


def _user_baseline_weight(user: User) -> float | None:
    if user.initial_weight_kg is not None:
        return float(user.initial_weight_kg)
    if user.weight_kg is not None:
        return float(user.weight_kg)
    return None


def _latest_weight_as_of(
    db: Session,
    user_id: int,
    as_of_date: date,
    baseline_weight: float | None = None,
) -> dict | None:
    record = (
        db.query(DailyWeight)
        .filter(DailyWeight.user_id == user_id, DailyWeight.entry_date <= as_of_date)
        .order_by(DailyWeight.entry_date.desc())
        .first()
    )
    if record:
        return {
            "weight_kg": record.weight_kg,
            "entry_date": record.entry_date.isoformat(),
            "logged_on_selected_date": record.entry_date == as_of_date,
            "source": "daily",
        }
    if baseline_weight is not None:
        return {
            "weight_kg": baseline_weight,
            "entry_date": None,
            "logged_on_selected_date": False,
            "source": "initial",
        }
    return None


def _weight_trend(
    db: Session,
    user_id: int,
    end_date: date,
    baseline_weight: float | None = None,
    days: int = 5,
) -> list[dict]:
    start_date = end_date - timedelta(days=days)
    records = (
        db.query(DailyWeight)
        .filter(DailyWeight.user_id == user_id, DailyWeight.entry_date <= end_date)
        .order_by(DailyWeight.entry_date.asc())
        .all()
    )
    weights_by_date = {record.entry_date: record.weight_kg for record in records}

    latest = baseline_weight
    for record in records:
        if record.entry_date < start_date:
            latest = record.weight_kg

    trend = []
    for offset in range(days + 1):
        day = start_date + timedelta(days=offset)
        if day in weights_by_date:
            latest = weights_by_date[day]
        trend.append(
            {
                "date": day.isoformat(),
                "weight_kg": latest,
                "logged_today": day in weights_by_date,
            }
        )
    return trend


def _daily_steps_payload(record: DailySteps | None) -> dict | None:
    if record is None:
        return None
    return {
        "steps_count": record.steps_count,
        "calories_burned": record.calories_burned,
        "ai_explanation": record.ai_explanation,
        "updated_at": record.updated_at.isoformat(),
    }


def _macros_provided(protein: float | None, carbohydrates: float | None, fats: float | None) -> bool:
    return protein is not None and carbohydrates is not None and fats is not None


def _build_meal_nutrition(
    food_name: str,
    user: User,
    protein: float | None = None,
    carbohydrates: float | None = None,
    fats: float | None = None,
):
    if _macros_provided(protein, carbohydrates, fats):
        calories = calories_from_macros(protein, carbohydrates, fats)
        return CalorieEstimate(
            calories=calories,
            explanation=(
                f"Calories from your macros: {protein:g}g protein × 4 + {carbohydrates:g}g carbs × 4 + "
                f"{fats:g}g fat × 9 = {calories:g} kcal. Exact calculation — no estimate."
            ),
            ai_estimated=False,
            protein=round(protein, 1),
            carbohydrates=round(carbohydrates, 1),
            fats=round(fats, 1),
        )
    return estimate_meal_calories(food_name, user)


def _meal_to_dict(meal: Meal) -> dict:
    return {
        "id": meal.id,
        "food_name": meal.food_name,
        "calories": meal.calories,
        "protein": meal.protein,
        "carbohydrates": meal.carbohydrates,
        "fats": meal.fats,
        "logged_at": meal.logged_at.isoformat(),
    }


def _apply_meal_nutrition(meal: Meal, estimate) -> None:
    meal.calories = estimate.calories
    meal.protein = estimate.protein
    meal.carbohydrates = estimate.carbohydrates
    meal.fats = estimate.fats


def _meal_response(meal: Meal, ai_estimated: bool, explanation: str, **extra) -> dict:
    return {
        **_meal_to_dict(meal),
        "entry_type": "meal",
        "ai_estimated": ai_estimated,
        "ai_explanation": explanation,
        **extra,
    }


@app.on_event("startup")
def on_startup():
    logger.info("Starting Nutrition Tracker")
    init_db()
    db = SessionLocal()
    try:
        seed_test_user(db)
        recalculate_all_users_bmr(db)
    finally:
        db.close()
    logger.info("Database ready")


@app.get("/api/capabilities")
def get_capabilities():
    return {
        "capabilities": {
            "meal_edit": True,
            "meal_delete": True,
            "workout_edit": True,
            "workout_delete": True,
            "steps": True,
            "weight": True,
            "ai_insight": True,
            "daily_tips": True,
            "data_export": True,
            "data_import": True,
        }
    }


@app.get("/", response_class=HTMLResponse)
def serve_frontend(request: Request):
    context = {
        "request": request,
        **SEO_META,
        "og_url": str(request.base_url).rstrip("/"),
    }
    response = templates.TemplateResponse("index.html", context)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    email = str(payload.email).lower() if payload.email else None
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        name=payload.name.strip(),
        email=email,
        gender=payload.gender,
        birth_date=payload.birth_date,
        height_cm=payload.height_cm,
        weight_kg=payload.weight_kg,
        initial_weight_kg=payload.weight_kg,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Registration failed for username %s: %s", username, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        ) from exc
    db.refresh(user)
    apply_bmr_to_user(user)
    db.flush()
    db.commit()
    db.refresh(user)

    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@app.get("/api/auth/me")
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (
        current_user.bmr is None
        and current_user.birth_date is not None
        and current_user.weight_kg is not None
    ):
        apply_bmr_to_user(current_user)
        db.commit()
        db.refresh(current_user)
    return user_to_dict(current_user)


@app.put("/api/profile")
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    email = str(payload.email).lower() if payload.email else None
    if email:
        existing = db.query(User).filter(User.email == email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    current_user.name = payload.name.strip()
    current_user.email = email
    current_user.gender = payload.gender
    if payload.birth_date is not None:
        current_user.birth_date = payload.birth_date
    if payload.height_cm is not None:
        current_user.height_cm = payload.height_cm
    if payload.weight_kg is not None:
        current_user.weight_kg = payload.weight_kg
    apply_bmr_to_user(current_user)
    db.flush()
    db.commit()
    db.refresh(current_user)
    return user_to_dict(current_user)


@app.get("/api/summary")
def get_daily_summary(
    target_date: date = Query(default_factory=date.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    day_start = datetime.combine(target_date, dt_time.min)
    day_end = datetime.combine(target_date, dt_time.max)

    calories_consumed = (
        db.query(func.coalesce(func.sum(Meal.calories), 0.0))
        .filter(
            Meal.user_id == current_user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .scalar()
    )

    total_protein = (
        db.query(func.coalesce(func.sum(Meal.protein), 0.0))
        .filter(
            Meal.user_id == current_user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .scalar()
    )

    total_carbohydrates = (
        db.query(func.coalesce(func.sum(Meal.carbohydrates), 0.0))
        .filter(
            Meal.user_id == current_user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .scalar()
    )

    total_fats = (
        db.query(func.coalesce(func.sum(Meal.fats), 0.0))
        .filter(
            Meal.user_id == current_user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .scalar()
    )

    calories_burned = (
        db.query(func.coalesce(func.sum(Workout.calories_burned), 0.0))
        .filter(
            Workout.user_id == current_user.id,
            Workout.logged_at >= day_start,
            Workout.logged_at <= day_end,
        )
        .scalar()
    )

    meals = (
        db.query(Meal)
        .filter(
            Meal.user_id == current_user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .order_by(Meal.logged_at.desc())
        .all()
    )

    workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == current_user.id,
            Workout.logged_at >= day_start,
            Workout.logged_at <= day_end,
        )
        .order_by(Workout.logged_at.desc())
        .all()
    )

    net_calories = float(calories_consumed) - float(calories_burned)
    steps_record = (
        db.query(DailySteps)
        .filter(DailySteps.user_id == current_user.id, DailySteps.entry_date == target_date)
        .first()
    )
    weight_record = (
        db.query(DailyWeight)
        .filter(DailyWeight.user_id == current_user.id, DailyWeight.entry_date == target_date)
        .first()
    )
    steps_calories = float(steps_record.calories_burned) if steps_record else 0.0
    activity_calories_burned = float(calories_burned) + steps_calories
    bmr = float(current_user.bmr) if current_user.bmr is not None else None
    total_calories_out = (bmr + activity_calories_burned) if bmr is not None else None
    calorie_balance = (
        float(calories_consumed) - total_calories_out if total_calories_out is not None else None
    )

    return {
        "date": target_date.isoformat(),
        "calories_consumed": float(calories_consumed),
        "total_protein": float(total_protein),
        "total_carbohydrates": float(total_carbohydrates),
        "total_fats": float(total_fats),
        "calories_burned": float(calories_burned),
        "steps_calories_burned": steps_calories,
        "activity_calories_burned": activity_calories_burned,
        "net_calories": net_calories,
        "bmr": bmr,
        "total_calories_out": total_calories_out,
        "calorie_balance": calorie_balance,
        "bmr_explanation": current_user.bmr_explanation,
        "daily_steps": _daily_steps_payload(steps_record),
        "daily_weight": _daily_weight_payload(weight_record),
        "latest_weight": _latest_weight_as_of(
            db, current_user.id, target_date, _user_baseline_weight(current_user)
        ),
        "weight_trend": _weight_trend(
            db, current_user.id, target_date, _user_baseline_weight(current_user)
        ),
        "meals": [_meal_to_dict(meal) for meal in meals],
        "workouts": [
            {
                "id": workout.id,
                "activity_type": workout.activity_type,
                "calories_burned": workout.calories_burned,
                "logged_at": workout.logged_at.isoformat(),
            }
            for workout in workouts
        ],
    }


@app.get("/api/dates-with-data")
def get_dates_with_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    dates: set[date] = set()

    for (logged_at,) in db.query(Meal.logged_at).filter(Meal.user_id == current_user.id).all():
        entry_date = logged_at.date()
        if entry_date <= today:
            dates.add(entry_date)

    for (logged_at,) in db.query(Workout.logged_at).filter(Workout.user_id == current_user.id).all():
        entry_date = logged_at.date()
        if entry_date <= today:
            dates.add(entry_date)

    for (entry_date,) in db.query(DailySteps.entry_date).filter(DailySteps.user_id == current_user.id).all():
        if entry_date <= today:
            dates.add(entry_date)

    for (entry_date,) in db.query(DailyWeight.entry_date).filter(DailyWeight.user_id == current_user.id).all():
        if entry_date <= today:
            dates.add(entry_date)

    return {"dates": sorted(d.isoformat() for d in dates)}


@app.put("/api/weight")
def upsert_daily_weight(
    payload: WeightUpsert,
    target_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_not_future_date(target_date)

    record = (
        db.query(DailyWeight)
        .filter(DailyWeight.user_id == current_user.id, DailyWeight.entry_date == target_date)
        .first()
    )

    if record is None:
        record = DailyWeight(
            user_id=current_user.id,
            entry_date=target_date,
            weight_kg=payload.weight_kg,
        )
        db.add(record)
    else:
        record.weight_kg = payload.weight_kg
        record.updated_at = datetime.utcnow()

    if target_date == date.today():
        current_user.weight_kg = payload.weight_kg
        apply_bmr_to_user(current_user)

    db.flush()
    db.commit()
    db.refresh(record)
    return {
        "date": target_date.isoformat(),
        "daily_weight": _daily_weight_payload(record),
        "latest_weight": _latest_weight_as_of(
            db, current_user.id, target_date, _user_baseline_weight(current_user)
        ),
        "weight_trend": _weight_trend(
            db, current_user.id, target_date, _user_baseline_weight(current_user)
        ),
    }


@app.put("/api/steps")
def upsert_daily_steps(
    payload: StepsUpsert,
    target_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_not_future_date(target_date)

    record = (
        db.query(DailySteps)
        .filter(DailySteps.user_id == current_user.id, DailySteps.entry_date == target_date)
        .first()
    )

    if payload.steps_count == 0:
        if record is not None:
            db.delete(record)
            db.commit()
        return {"date": target_date.isoformat(), "daily_steps": None}

    workouts = _workouts_for_date(db, current_user.id, target_date)
    estimate = estimate_steps_calories(current_user, payload.steps_count, workouts)

    if record is None:
        record = DailySteps(
            user_id=current_user.id,
            entry_date=target_date,
            steps_count=payload.steps_count,
            calories_burned=estimate.calories_burned,
            ai_explanation=estimate.explanation,
        )
        db.add(record)
    else:
        record.steps_count = payload.steps_count
        record.calories_burned = estimate.calories_burned
        record.ai_explanation = estimate.explanation
        record.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(record)
    return {
        "date": target_date.isoformat(),
        "daily_steps": _daily_steps_payload(record),
        "ai_estimated": estimate.ai_estimated,
        "ai_explanation": estimate.explanation,
    }


@app.get("/api/daily-tips")
def get_daily_tips(
    language: str = Query(default="en", pattern=r"^(en|he)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = get_or_create_daily_tips(
        current_user,
        db,
        language=language,
        force_refresh=False,
        api_key=GEMINI_API_KEY,
    )
    db.commit()
    return result


@app.post("/api/daily-tips/refresh")
def refresh_daily_tips(
    payload: DailyTipsRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request = payload or DailyTipsRequest()
    result = get_or_create_daily_tips(
        current_user,
        db,
        language=request.language,
        force_refresh=True,
        api_key=GEMINI_API_KEY,
    )
    db.commit()
    logger.info("Refreshed daily tips for %s (%s)", current_user.username, request.language)
    return result


@app.post("/api/ai-insight")
def get_ai_insight(
    payload: InsightRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request = payload or InsightRequest()
    target_date = request.target_date or date.today()
    return generate_daily_insight(
        current_user,
        db,
        target_date,
        request.language,
        api_key=GEMINI_API_KEY,
    )


@app.post("/api/meals", status_code=201)
def add_meal(
    payload: MealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    estimate = _build_meal_nutrition(
        payload.food_name.strip(),
        current_user,
        payload.protein,
        payload.carbohydrates,
        payload.fats,
    )
    meal = Meal(
        user_id=current_user.id,
        food_name=payload.food_name.strip(),
        calories=estimate.calories,
        protein=estimate.protein,
        carbohydrates=estimate.carbohydrates,
        fats=estimate.fats,
        logged_at=_ensure_not_future_logged_at(payload.logged_at),
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return _meal_response(meal, estimate.ai_estimated, estimate.explanation)


@app.post("/api/workouts", status_code=201)
def add_workout(
    payload: WorkoutCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    estimate = _estimate_workout_calories(db, current_user, payload.activity_type.strip())
    workout = Workout(
        user_id=current_user.id,
        activity_type=payload.activity_type.strip(),
        calories_burned=estimate.calories,
        logged_at=_ensure_not_future_logged_at(payload.logged_at),
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)
    _refresh_daily_steps_calories(db, current_user, workout.logged_at.date())
    db.commit()
    return {
        "id": workout.id,
        "activity_type": workout.activity_type,
        "calories_burned": workout.calories_burned,
        "logged_at": workout.logged_at.isoformat(),
        "entry_type": "workout",
        "ai_estimated": estimate.ai_estimated,
        "ai_explanation": estimate.explanation,
    }


@app.put("/api/meals/{meal_id}")
def update_meal(
    meal_id: int,
    payload: MealUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meal = _get_user_meal(meal_id, current_user, db)
    new_name = payload.food_name.strip()
    name_changed = new_name != meal.food_name

    meal.food_name = new_name
    if payload.logged_at is not None:
        meal.logged_at = _ensure_not_future_logged_at(payload.logged_at)

    ai_estimated = False
    explanation = ""
    if payload.recalculate_calories or name_changed:
        estimate = _build_meal_nutrition(new_name, current_user)
        _apply_meal_nutrition(meal, estimate)
        ai_estimated = estimate.ai_estimated
        explanation = estimate.explanation
    elif _macros_provided(payload.protein, payload.carbohydrates, payload.fats):
        estimate = _build_meal_nutrition(
            new_name,
            current_user,
            payload.protein,
            payload.carbohydrates,
            payload.fats,
        )
        _apply_meal_nutrition(meal, estimate)
        ai_estimated = estimate.ai_estimated
        explanation = estimate.explanation

    db.commit()
    db.refresh(meal)
    return _meal_response(
        meal,
        ai_estimated,
        explanation,
        calories_recalculated=payload.recalculate_calories or name_changed,
    )


@app.delete("/api/meals/{meal_id}")
def delete_meal(
    meal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meal = _get_user_meal(meal_id, current_user, db)
    db.delete(meal)
    db.commit()
    logger.info("Deleted meal %s for user %s", meal_id, current_user.username)
    return {"id": meal_id, "deleted": True}


@app.put("/api/workouts/{workout_id}")
def update_workout(
    workout_id: int,
    payload: WorkoutUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workout = _get_user_workout(workout_id, current_user, db)
    previous_date = workout.logged_at.date()
    new_activity = payload.activity_type.strip()
    activity_changed = new_activity != workout.activity_type

    workout.activity_type = new_activity
    if payload.logged_at is not None:
        workout.logged_at = _ensure_not_future_logged_at(payload.logged_at)

    ai_estimated = False
    explanation = ""
    if payload.recalculate_calories or activity_changed:
        estimate = _estimate_workout_calories(
            db,
            current_user,
            new_activity,
            exclude_workout_id=workout.id,
            allow_reuse=not payload.recalculate_calories,
        )
        workout.calories_burned = estimate.calories
        ai_estimated = estimate.ai_estimated
        explanation = estimate.explanation

    db.commit()
    db.refresh(workout)
    _refresh_daily_steps_calories(db, current_user, workout.logged_at.date())
    if workout.logged_at.date() != previous_date:
        _refresh_daily_steps_calories(db, current_user, previous_date)
    db.commit()
    return {
        "id": workout.id,
        "activity_type": workout.activity_type,
        "calories_burned": workout.calories_burned,
        "logged_at": workout.logged_at.isoformat(),
        "entry_type": "workout",
        "ai_estimated": ai_estimated,
        "ai_explanation": explanation,
        "calories_recalculated": payload.recalculate_calories or activity_changed,
    }


@app.delete("/api/workouts/{workout_id}")
def delete_workout(
    workout_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workout = _get_user_workout(workout_id, current_user, db)
    workout_date = workout.logged_at.date()
    db.delete(workout)
    db.commit()
    _refresh_daily_steps_calories(db, current_user, workout_date)
    db.commit()
    logger.info("Deleted workout %s for user %s", workout_id, current_user.username)
    return {"id": workout_id, "deleted": True}


@app.get("/api/user-data/export")
def export_user_data(
    export_format: Literal["json", "csv"] = Query("json", alias="format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_for_download),
):
    filename_base = f"nutrition-tracker-{current_user.username}"
    if export_format == "csv":
        content = export_csv(current_user, db)
        return Response(
            content=content.encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.csv"',
                "Cache-Control": "no-store",
            },
        )

    content = export_json(current_user, db)
    return Response(
        content=content.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.json"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/user-data/import/preview")
async def preview_user_data_import(
    request: Request,
    import_format: Literal["json", "csv"] = Query("json", alias="format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = await request.body()
    try:
        if import_format == "csv":
            payload = parse_csv_payload(body.decode("utf-8-sig"))
        else:
            payload = parse_json_payload(json.loads(body.decode("utf-8")))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid JSON payload",
        ) from exc

    return preview_import(current_user, db, payload)


@app.post("/api/user-data/import")
async def import_user_data(
    apply_request: ImportApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    resolutions = apply_request.resolutions.model_dump() if apply_request.resolutions else None
    try:
        if apply_request.format == "csv":
            result = import_csv_payload(
                current_user,
                db,
                apply_request.content,
                mode=apply_request.mode,
                resolutions=resolutions,
            )
        else:
            payload = parse_json_payload(json.loads(apply_request.content))
            result = import_json_payload(
                current_user,
                db,
                payload,
                mode=apply_request.mode,
                resolutions=resolutions,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid JSON payload",
        ) from exc

    db.commit()
    db.refresh(current_user)
    logger.info("Imported user data for %s: %s", current_user.username, result.to_dict())
    return result.to_dict()
