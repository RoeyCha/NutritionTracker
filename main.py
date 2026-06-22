from datetime import date, datetime, time
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Meal, SessionLocal, User, Workout, init_db

app = FastAPI(title="Nutrition Tracker MVP")
templates = Jinja2Templates(directory="templates")

BASE_DIR = Path(__file__).resolve().parent
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_default_user(db: Session) -> User:
    user = db.query(User).filter(User.email == "demo@example.com").first()
    if user is None:
        user = User(name="Demo User", email="demo@example.com")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


class MealCreate(BaseModel):
    food_name: str = Field(..., min_length=1, max_length=200)
    calories: float = Field(..., gt=0)
    logged_at: datetime | None = None


class WorkoutCreate(BaseModel):
    activity_type: str = Field(..., min_length=1, max_length=200)
    calories_burned: float = Field(..., gt=0)
    logged_at: datetime | None = None


@app.on_event("startup")
def on_startup():
    init_db()
    db = SessionLocal()
    try:
        get_or_create_default_user(db)
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def serve_frontend(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/summary")
def get_daily_summary(
    target_date: date = Query(default_factory=date.today, alias="date"),
    db: Session = Depends(get_db),
):
    user = get_or_create_default_user(db)
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    calories_consumed = (
        db.query(func.coalesce(func.sum(Meal.calories), 0.0))
        .filter(
            Meal.user_id == user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .scalar()
    )

    calories_burned = (
        db.query(func.coalesce(func.sum(Workout.calories_burned), 0.0))
        .filter(
            Workout.user_id == user.id,
            Workout.logged_at >= day_start,
            Workout.logged_at <= day_end,
        )
        .scalar()
    )

    meals = (
        db.query(Meal)
        .filter(
            Meal.user_id == user.id,
            Meal.logged_at >= day_start,
            Meal.logged_at <= day_end,
        )
        .order_by(Meal.logged_at.desc())
        .all()
    )

    workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == user.id,
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


@app.post("/api/meals", status_code=201)
def add_meal(payload: MealCreate, db: Session = Depends(get_db)):
    user = get_or_create_default_user(db)
    meal = Meal(
        user_id=user.id,
        food_name=payload.food_name.strip(),
        calories=payload.calories,
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
    }


@app.post("/api/workouts", status_code=201)
def add_workout(payload: WorkoutCreate, db: Session = Depends(get_db)):
    user = get_or_create_default_user(db)
    workout = Workout(
        user_id=user.id,
        activity_type=payload.activity_type.strip(),
        calories_burned=payload.calories_burned,
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
    }
