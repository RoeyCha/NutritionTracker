import json
import logging
import os
import re
from dataclasses import dataclass

import google.generativeai as genai

from gemini_insight import GEMINI_MODEL, GEMINI_MODEL_FALLBACKS
from models import User

logger = logging.getLogger(__name__)


@dataclass
class CalorieEstimate:
    calories: float
    explanation: str
    ai_estimated: bool


def _user_context(user: User) -> str:
    parts = []
    if user.age is not None:
        parts.append(f"age {user.age}")
    if user.weight_kg is not None:
        parts.append(f"weight {user.weight_kg} kg")
    if user.gender:
        parts.append(f"gender {user.gender}")
    return ", ".join(parts) if parts else "average adult"


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _gemini_estimate(prompt: str) -> CalorieEstimate:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    full_prompt = (
        "You estimate calories for nutrition tracking. "
        "Respond with JSON only using keys: calories (number), explanation (string). "
        "Calories must be a positive number with at most one decimal place.\n\n"
        f"{prompt}"
    )

    preferred_model = os.getenv("GEMINI_MODEL", GEMINI_MODEL)
    model_names = []
    for name in (preferred_model, *GEMINI_MODEL_FALLBACKS):
        if name not in model_names:
            model_names.append(name)

    genai.configure(api_key=api_key)
    last_error = None
    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(full_prompt)
            data = _extract_json(response.text or "{}")
            calories = float(data["calories"])
            if calories <= 0:
                raise ValueError("Calories must be positive")
            logger.info("Gemini calorie estimate succeeded with model %s", model_name)
            return CalorieEstimate(
                calories=round(calories, 1),
                explanation=str(data.get("explanation", "")).strip(),
                ai_estimated=True,
            )
        except Exception as exc:
            logger.warning("Gemini model %s failed: %s", model_name, exc)
            last_error = exc
            continue
    raise last_error or RuntimeError("No Gemini model available")


def _fallback_meal_estimate(food_name: str) -> CalorieEstimate:
    text = food_name.lower()
    rules = [
        (r"salad|סלט", 380),
        (r"chicken|עוף", 450),
        (r"rice|אורז", 320),
        (r"pizza|פיצה", 650),
        (r"burger|המבורגר", 720),
        (r"oatmeal|שיבולת|דייס", 350),
        (r"yogurt|יוגורט", 180),
        (r"soup|מרק", 250),
        (r"fish|salmon|דג|סלמון", 520),
        (r"steak|בשר", 600),
        (r"apple|banana|fruit|תפוח|בננה|פרי", 95),
        (r"coffee|קפה", 25),
        (r"sandwich|כריך", 420),
    ]
    for pattern, calories in rules:
        if re.search(pattern, text):
            return CalorieEstimate(
                calories=float(calories),
                explanation="Local estimate based on typical portion size.",
                ai_estimated=False,
            )
    return CalorieEstimate(
        calories=400.0,
        explanation="Local default estimate for a typical single serving.",
        ai_estimated=False,
    )


def _fallback_workout_estimate(activity_type: str, user: User) -> CalorieEstimate:
    text = activity_type.lower()
    weight = user.weight_kg or 70.0
    base = max(120.0, weight * 3.5)
    rules = [
        (r"run|ריצ", 1.4),
        (r"walk|הליכ", 0.7),
        (r"swim|שחי", 1.3),
        (r"cycle|bike|אופנ", 1.2),
        (r"weight|gym|כושר|משקול", 1.0),
        (r"yoga|יוג", 0.5),
        (r"hiit|interval", 1.5),
    ]
    multiplier = 1.0
    for pattern, factor in rules:
        if re.search(pattern, text):
            multiplier = factor
            break

    duration_match = re.search(r"(\d+)\s*(min|minutes|minute|דק)", text)
    if duration_match:
        minutes = int(duration_match.group(1))
        calories = base * multiplier * (minutes / 30)
    else:
        calories = base * multiplier

    return CalorieEstimate(
        calories=round(calories, 1),
        explanation="Local estimate based on activity type and profile.",
        ai_estimated=False,
    )


def estimate_meal_calories(food_name: str, user: User) -> CalorieEstimate:
    prompt = (
        f'Estimate calories consumed for this meal: "{food_name}".\n'
        f"User profile: {_user_context(user)}.\n"
        "Assume a typical single serving unless the description specifies otherwise."
    )
    try:
        return _gemini_estimate(prompt)
    except Exception as exc:
        logger.warning(
            "Meal calorie AI failed for %r, using local fallback: %s",
            food_name,
            exc,
            exc_info=True,
        )
        return _fallback_meal_estimate(food_name)


def estimate_workout_calories(activity_type: str, user: User) -> CalorieEstimate:
    prompt = (
        f'Estimate calories burned for this activity: "{activity_type}".\n'
        f"User profile: {_user_context(user)}.\n"
        "If duration is not specified, assume a moderate 30-minute session."
    )
    try:
        return _gemini_estimate(prompt)
    except Exception as exc:
        logger.warning(
            "Workout calorie AI failed for %r, using local fallback: %s",
            activity_type,
            exc,
            exc_info=True,
        )
        return _fallback_workout_estimate(activity_type, user)
