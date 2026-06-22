from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from auth import hash_password
from models import Meal, User, Workout


def seed_test_user(db: Session) -> User:
    user = db.query(User).filter(User.username == "test").first()
    if user is not None:
        if user.gender is None and user.age is None and user.weight_kg is None:
            user.gender = "male"
            user.age = 30
            user.weight_kg = 75.0
            db.commit()
            db.refresh(user)
        return user

    user = User(
        username="test",
        password_hash=hash_password("1234"),
        name="Test User",
        email="test@example.com",
        gender="male",
        age=30,
        weight_kg=75.0,
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
    db.commit()
    db.refresh(user)
    return user
