import json
import os
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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
from auth import (
    create_access_token,
    get_current_user,
    get_db,
    hash_password,
    user_to_dict,
    verify_password,
)
from models import Meal, SessionLocal, User, Workout, init_db
from seed import seed_test_user


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


class InsightRequest(BaseModel):
    date: date | None = None
    language: str = Field(default="en", pattern=r"^(en|he)$")


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        seed_test_user(db)
    finally:
        db.close()


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
    db.commit()
    db.refresh(current_user)
    return user_to_dict(current_user)


@app.get("/api/summary")
def get_daily_summary(
    target_date: date = Query(default_factory=date.today, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

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

    return {
        "date": target_date.isoformat(),
        "calories_consumed": float(calories_consumed),
        "calories_burned": float(calories_burned),
        "net_calories": net_calories,
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


@app.post("/api/ai-insight")
def get_ai_insight(
    payload: InsightRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request = payload or InsightRequest()
    target_date = request.date or date.today()
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
        logged_at=payload.logged_at or datetime.utcnow(),
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
        logged_at=payload.logged_at or datetime.utcnow(),
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return {
        "id": workout.id,
        "activity_type": workout.activity_type,
        "calories_burned": workout.calories_burned,
        "logged_at": workout.logged_at.isoformat(),
        "entry_type": "workout",
        "ai_estimated": estimate.ai_estimated,
        "ai_explanation": estimate.explanation,
    }
