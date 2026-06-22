import json
import logging
import os
import re
from datetime import date

import google.generativeai as genai
from sqlalchemy.orm import Session

from models import Meal, User, Workout

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODEL_FALLBACKS = ("gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite")


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


def _fallback_daily_insight(logs: dict, language: str) -> dict:
    consumed = logs["calories_consumed"]
    burned = logs["calories_burned"]
    meal_count = len(logs["meals"])
    workout_count = len(logs["workouts"])

    if language == "he":
        if meal_count == 0 and workout_count == 0:
            feedback = "עדיין לא נרשמו ארוחות או אימונים ליום זה. התחלת רישום קטנה עוזרת לבנות הרגל בריא."
            tip = "נסה לרשום את הארוחה או הפעילות הבאה מיד אחריה."
        elif consumed > burned + 400:
            feedback = f"רשמת {meal_count} ארוחות ו-{workout_count} אימונים. צריכת הקלוריות גבוהה מהפעילות — זה בסדר, העיקר עקביות."
            tip = "שקול הליכה קצרה או ארוחה קלה יותר בערב."
        elif burned > consumed:
            feedback = f"יום פעיל! שרפת יותר קלוריות ({burned:.0f}) ממה שצרכת ({consumed:.0f})."
            tip = "ודא שאתה מקבל מספיק חלבון ומים לאחר האימון."
        else:
            feedback = f"יום מאוזן עם {meal_count} ארוחות ו-{workout_count} אימונים. המשך לעקוב אחרי ההרגלים שלך."
            tip = "שמור על שתייה מספקת לאורך היום."
    else:
        if meal_count == 0 and workout_count == 0:
            feedback = "No meals or workouts logged yet for this day. Small consistent tracking builds healthy habits."
            tip = "Try logging your next meal or activity right after it happens."
        elif consumed > burned + 400:
            feedback = (
                f"You logged {meal_count} meals and {workout_count} workouts. "
                "Calorie intake is higher than activity today — consistency matters more than perfection."
            )
            tip = "Consider a short walk or a lighter evening meal."
        elif burned > consumed:
            feedback = (
                f"Active day! You burned more calories ({burned:.0f}) than you consumed ({consumed:.0f})."
            )
            tip = "Make sure you get enough protein and water after exercise."
        else:
            feedback = (
                f"Balanced day with {meal_count} meals and {workout_count} workouts. "
                "Keep building on your tracking habit."
            )
            tip = "Stay hydrated throughout the day."

    return {"feedback": feedback, "health_tip": tip}


def generate_daily_insight(
    user: User,
    db: Session,
    target_date: date,
    language: str = "en",
    api_key: str | None = None,
) -> dict:
    logs = fetch_daily_logs(db, user, target_date)
    api_key = api_key or os.getenv("GEMINI_API_KEY")

    if not api_key:
        logger.info("No GEMINI_API_KEY — returning local daily insight for %s", user.username)
        parsed = _fallback_daily_insight(logs, language)
        return {
            "date": logs["date"],
            "feedback": parsed["feedback"],
            "health_tip": parsed["health_tip"],
            "summary": logs,
            "model": "local-fallback",
            "ai_estimated": False,
        }

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
                logger.info("Gemini daily insight succeeded with model %s for %s", model_name, user.username)
                return {
                    "date": logs["date"],
                    "feedback": parsed["feedback"],
                    "health_tip": parsed["health_tip"],
                    "summary": logs,
                    "model": model_name,
                    "ai_estimated": True,
                }
            except Exception as exc:
                logger.warning("Gemini insight model %s failed: %s", model_name, exc)
                last_error = exc
                continue
        raise last_error or RuntimeError("No Gemini model available")
    except Exception as exc:
        logger.warning(
            "Daily insight AI failed for %s, using local fallback: %s",
            user.username,
            exc,
            exc_info=True,
        )
        parsed = _fallback_daily_insight(logs, language)
        return {
            "date": logs["date"],
            "feedback": parsed["feedback"],
            "health_tip": parsed["health_tip"],
            "summary": logs,
            "model": "local-fallback",
            "ai_estimated": False,
        }
