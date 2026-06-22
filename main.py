import json
import logging
import os
import time
from datetime import date, datetime, time as dt_time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app_logging import setup_logging

setup_logging()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from gemini_insight import generate_daily_insight
from ai_calories import estimate_meal_calories, estimate_workout_calories
from bmr_calculator import apply_bmr_to_user
from auth import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    user_to_dict,
    verify_password,
)
from models import DailySteps, Meal, SessionLocal, User, Workout, init_db
from seed import seed_test_user
from steps_calories import estimate_steps_calories

logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")


app = FastAPI(title="Nutrition Tracker MVP", default_response_class=UTF8JSONResponse)
templates = Jinja2Templates(directory="templates")

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
    age: int | None = Field(default=None, ge=1, le=120)
    weight_kg: float | None = Field(default=None, gt=0, le=500)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class ProfileUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr | None = None
    gender: str | None = Field(default=None, pattern=r"^(male|female|other)$")
    age: int | None = Field(default=None, ge=1, le=120)
    weight_kg: float | None = Field(default=None, gt=0, le=500)

    @field_validator("gender", mode="before")
    @classmethod
    def empty_gender_to_none(cls, value):
        if value == "":
            return None
        return value


class MealCreate(BaseModel):
    food_name: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None


class WorkoutCreate(BaseModel):
    activity_type: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None


class MealUpdate(BaseModel):
    food_name: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None
    recalculate_calories: bool = False


class WorkoutUpdate(BaseModel):
    activity_type: str = Field(..., min_length=1, max_length=200)
    logged_at: datetime | None = None
    recalculate_calories: bool = False


class InsightRequest(BaseModel):
    target_date: date | None = Field(default=None, alias="date")
    language: str = Field(default="en", pattern=r"^(en|he)$")

    model_config = {"populate_by_name": True}


class StepsUpsert(BaseModel):
    steps_count: int = Field(..., ge=0, le=100000)


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


def _daily_steps_payload(record: DailySteps | None) -> dict | None:
    if record is None:
        return None
    return {
        "steps_count": record.steps_count,
        "calories_burned": record.calories_burned,
        "ai_explanation": record.ai_explanation,
        "updated_at": record.updated_at.isoformat(),
    }


@app.on_event("startup")
def on_startup():
    logger.info("Starting Nutrition Tracker")
    init_db()
    db = SessionLocal()
    try:
        seed_test_user(db)
    finally:
        db.close()
    logger.info("Database ready")


@app.get("/", response_class=HTMLResponse)
def serve_frontend(request: Request):
    response = templates.TemplateResponse("index.html", {"request": request})
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
        age=payload.age,
        weight_kg=payload.weight_kg,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    apply_bmr_to_user(user)
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
def get_me(current_user: User = Depends(get_current_user)):
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
    current_user.age = payload.age
    current_user.weight_kg = payload.weight_kg
    apply_bmr_to_user(current_user)
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
        "calories_burned": float(calories_burned),
        "steps_calories_burned": steps_calories,
        "activity_calories_burned": activity_calories_burned,
        "net_calories": net_calories,
        "bmr": bmr,
        "total_calories_out": total_calories_out,
        "calorie_balance": calorie_balance,
        "bmr_explanation": current_user.bmr_explanation,
        "daily_steps": _daily_steps_payload(steps_record),
        "meals": [
            {
                "id": meal.id,
                "food_name": meal.food_name,
                "calories": meal.calories,
                "logged_at": meal.logged_at.isoformat(),
            }
            for meal in meals
        ],
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

    return {"dates": sorted(d.isoformat() for d in dates)}


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
    estimate = estimate_meal_calories(payload.food_name.strip(), current_user)
    meal = Meal(
        user_id=current_user.id,
        food_name=payload.food_name.strip(),
        calories=estimate.calories,
        logged_at=_ensure_not_future_logged_at(payload.logged_at),
    )
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return {
        "id": meal.id,
        "food_name": meal.food_name,
        "calories": meal.calories,
        "logged_at": meal.logged_at.isoformat(),
        "entry_type": "meal",
        "ai_estimated": estimate.ai_estimated,
        "ai_explanation": estimate.explanation,
    }


@app.post("/api/workouts", status_code=201)
def add_workout(
    payload: WorkoutCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    estimate = estimate_workout_calories(payload.activity_type.strip(), current_user)
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
        estimate = estimate_meal_calories(new_name, current_user)
        meal.calories = estimate.calories
        ai_estimated = estimate.ai_estimated
        explanation = estimate.explanation

    db.commit()
    db.refresh(meal)
    return {
        "id": meal.id,
        "food_name": meal.food_name,
        "calories": meal.calories,
        "logged_at": meal.logged_at.isoformat(),
        "entry_type": "meal",
        "ai_estimated": ai_estimated,
        "ai_explanation": explanation,
        "calories_recalculated": payload.recalculate_calories or name_changed,
    }


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
        estimate = estimate_workout_calories(new_activity, current_user)
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
