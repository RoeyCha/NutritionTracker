import json
import os
import re
from datetime import date

import google.generativeai as genai
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import Meal, User, Workout

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_MODEL_FALLBACKS = ("gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-pro")


def fetch_daily_logs(db: Session, user: User, target_date: date) -> dict:
    from datetime import datetime, time

    from sqlalchemy import func

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
        .order_by(Meal.logged_at.asc())
        .all()
    )

    workouts = (
        db.query(Workout)
        .filter(
            Workout.user_id == user.id,
            Workout.logged_at >= day_start,
            Workout.logged_at <= day_end,
        )
        .order_by(Workout.logged_at.asc())
        .all()
    )

    consumed = float(calories_consumed)
    burned = float(calories_burned)

    return {
        "date": target_date.isoformat(),
        "calories_consumed": consumed,
        "calories_burned": burned,
        "net_calories": consumed - burned,
        "meals": [{"food_name": meal.food_name, "calories": meal.calories} for meal in meals],
        "workouts": [
            {"activity_type": workout.activity_type, "calories_burned": workout.calories_burned}
            for workout in workouts
        ],
    }


def _user_profile_text(user: User) -> str:
    parts = [f"Name: {user.name}"]
    if user.age is not None:
        parts.append(f"Age: {user.age}")
    if user.weight_kg is not None:
        parts.append(f"Weight: {user.weight_kg} kg")
    if user.gender:
        parts.append(f"Gender: {user.gender}")
    return ", ".join(parts)


def _build_prompt(user: User, logs: dict, language: str) -> str:
    meal_lines = [
        f"- {meal['food_name']} ({meal['calories']} cal)" for meal in logs["meals"]
    ] or ["- No meals logged"]
    workout_lines = [
        f"- {workout['activity_type']} ({workout['calories_burned']} cal burned)"
        for workout in logs["workouts"]
    ] or ["- No workouts logged"]

    language_instruction = (
        "Respond in Hebrew."
        if language == "he"
        else "Respond in English."
    )

    return f"""You are a supportive nutrition and fitness coach.

Review this user's daily nutrition and activity log and provide:
1. A short, encouraging feedback paragraph (2-3 sentences max).
2. One practical health tip tailored to their day.

{language_instruction}

User profile: {_user_profile_text(user)}
Date: {logs['date']}
Calories consumed: {logs['calories_consumed']}
Calories burned: {logs['calories_burned']}
Net calories: {logs['net_calories']}

Meals:
{chr(10).join(meal_lines)}

Workouts:
{chr(10).join(workout_lines)}

Return JSON only with this exact shape:
{{"feedback": "...", "health_tip": "..."}}
"""


def _parse_gemini_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    feedback = str(data.get("feedback", "")).strip()
    health_tip = str(data.get("health_tip", "")).strip()
    if not feedback or not health_tip:
        raise ValueError("Missing feedback or health_tip")
    return {"feedback": feedback, "health_tip": health_tip}


def generate_daily_insight(
    user: User,
    db: Session,
    target_date: date,
    language: str = "en",
    api_key: str | None = None,
) -> dict:
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured.",
        )

    logs = fetch_daily_logs(db, user, target_date)
    prompt = _build_prompt(user, logs, language)

    preferred_model = os.getenv("GEMINI_MODEL", GEMINI_MODEL)
    model_names = []
    for name in (preferred_model, *GEMINI_MODEL_FALLBACKS):
        if name not in model_names:
            model_names.append(name)

    last_error = None
    try:
        genai.configure(api_key=api_key)
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                parsed = _parse_gemini_json(response.text or "")
                return {
                    "date": logs["date"],
                    "feedback": parsed["feedback"],
                    "health_tip": parsed["health_tip"],
                    "summary": logs,
                    "model": model_name,
                }
            except Exception as exc:
                last_error = exc
                continue
        raise last_error or RuntimeError("No Gemini model available")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate AI insight. Please try again shortly.",
        ) from exc
