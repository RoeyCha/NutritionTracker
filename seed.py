from datetime import date, datetime, timedelta, time

from sqlalchemy.orm import Session

from auth import hash_password
from bmr_calculator import apply_bmr_to_user
from models import DailySteps, Meal, User, Workout
from steps_calories import estimate_steps_calories


def _default_birth_date_for_age(age: int) -> date:
    return date.today() - timedelta(days=365 * age)


def seed_test_user(db: Session) -> User:
    user = db.query(User).filter(User.username == "test").first()
    if user is not None:
        if user.gender is None and user.birth_date is None and user.weight_kg is None:
            user.gender = "male"
            user.birth_date = _default_birth_date_for_age(30)
            user.height_cm = 175.0
            user.weight_kg = 75.0
            user.initial_weight_kg = 75.0
            apply_bmr_to_user(user)
            db.commit()
            db.refresh(user)
        elif user.bmr is None and user.birth_date is not None and user.weight_kg is not None:
            apply_bmr_to_user(user)
            db.commit()
            db.refresh(user)
        return user

    user = User(
        username="test",
        password_hash=hash_password("1234"),
        name="Test User",
        email="test@example.com",
        gender="male",
        birth_date=_default_birth_date_for_age(30),
        height_cm=175.0,
        weight_kg=75.0,
        initial_weight_kg=75.0,
    )
    db.add(user)
    db.flush()

    now = datetime.utcnow()
    breakfast = now.replace(hour=8, minute=30, second=0, microsecond=0)
    lunch = now.replace(hour=13, minute=0, second=0, microsecond=0)
    snack = now.replace(hour=16, minute=15, second=0, microsecond=0)
    dinner = now.replace(hour=19, minute=45, second=0, microsecond=0)
    morning_run = now.replace(hour=7, minute=0, second=0, microsecond=0)
    gym = now.replace(hour=17, minute=30, second=0, microsecond=0)
    yesterday_lunch = (now - timedelta(days=1)).replace(hour=12, minute=30, second=0, microsecond=0)
    yesterday_walk = (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)

    dummy_meals = [
        Meal(user_id=user.id, food_name="Oatmeal with berries", calories=350, logged_at=breakfast),
        Meal(user_id=user.id, food_name="Grilled chicken salad", calories=520, logged_at=lunch),
        Meal(user_id=user.id, food_name="Greek yogurt", calories=180, logged_at=snack),
        Meal(user_id=user.id, food_name="Salmon and rice", calories=640, logged_at=dinner),
        Meal(user_id=user.id, food_name="Vegetable soup", calories=290, logged_at=yesterday_lunch),
    ]
    dummy_workouts = [
        Workout(user_id=user.id, activity_type="Morning run", calories_burned=280, logged_at=morning_run),
        Workout(user_id=user.id, activity_type="Weight training", calories_burned=220, logged_at=gym),
        Workout(user_id=user.id, activity_type="Evening walk", calories_burned=150, logged_at=yesterday_walk),
    ]

    db.add_all(dummy_meals + dummy_workouts)
    db.add(
        DailySteps(
            user_id=user.id,
            entry_date=now.date(),
            steps_count=8500,
            calories_burned=0.0,
        )
    )
    apply_bmr_to_user(user)
    db.commit()
    db.refresh(user)

    steps_record = (
        db.query(DailySteps)
        .filter(DailySteps.user_id == user.id, DailySteps.entry_date == now.date())
        .first()
    )
    if steps_record:
        day_start = datetime.combine(now.date(), time.min)
        day_end = datetime.combine(now.date(), time.max)
        day_workouts = (
            db.query(Workout)
            .filter(
                Workout.user_id == user.id,
                Workout.logged_at >= day_start,
                Workout.logged_at <= day_end,
            )
            .all()
        )
        workout_payload = [
            {"activity_type": workout.activity_type, "calories_burned": workout.calories_burned}
            for workout in day_workouts
        ]
        estimate = estimate_steps_calories(user, steps_record.steps_count, workout_payload)
        steps_record.calories_burned = estimate.calories_burned
        steps_record.ai_explanation = estimate.explanation
        db.commit()
    db.refresh(user)
    return user


def seed_admin_user(db: Session) -> User:
    user = db.query(User).filter(User.username == "admin").first()
    if user is not None:
        if not user.is_admin:
            user.is_admin = True
        if not user.is_active:
            user.is_active = True
        user.password_hash = hash_password("Admin1234!")
        db.commit()
        db.refresh(user)
        return user

    user = User(
        username="admin",
        password_hash=hash_password("Admin1234!"),
        name="Administrator",
        email=None,
        is_admin=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
