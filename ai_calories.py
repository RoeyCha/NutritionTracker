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
    protein: float = 0.0
    carbohydrates: float = 0.0
    fats: float = 0.0


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


def _macros_from_calories(
    calories: float,
    protein_pct: float = 0.25,
    carb_pct: float = 0.45,
    fat_pct: float = 0.30,
) -> tuple[float, float, float]:
    return (
        round(calories * protein_pct / 4, 1),
        round(calories * carb_pct / 4, 1),
        round(calories * fat_pct / 9, 1),
    )


def _gemini_calorie_estimate(prompt: str) -> CalorieEstimate:
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


def _gemini_meal_estimate(prompt: str) -> CalorieEstimate:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    full_prompt = (
        "You estimate nutrition for a meal in a food tracking app. "
        "Respond with JSON only using keys: calories (number), protein (number), "
        "carbohydrates (number), fats (number), explanation (string). "
        "All values must be >= 0 with at most one decimal place. "
        "Protein, carbohydrates, and fats are in grams.\n\n"
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
            protein = float(data["protein"])
            carbohydrates = float(data["carbohydrates"])
            fats = float(data["fats"])
            if calories <= 0 or protein < 0 or carbohydrates < 0 or fats < 0:
                raise ValueError("Nutrition values must be valid")
            logger.info("Gemini meal estimate succeeded with model %s", model_name)
            return CalorieEstimate(
                calories=round(calories, 1),
                explanation=str(data.get("explanation", "")).strip(),
                ai_estimated=True,
                protein=round(protein, 1),
                carbohydrates=round(carbohydrates, 1),
                fats=round(fats, 1),
            )
        except Exception as exc:
            logger.warning("Gemini meal model %s failed: %s", model_name, exc)
            last_error = exc
            continue
    raise last_error or RuntimeError("No Gemini model available")


def _fallback_meal_estimate(food_name: str) -> CalorieEstimate:
    text = food_name.lower()
    rules = [
        (r"salad|סלט", 380, 0.20, 0.35, 0.45),
        (r"chicken|עוף", 450, 0.45, 0.10, 0.45),
        (r"rice|אורז", 320, 0.10, 0.80, 0.10),
        (r"pizza|פיצה", 650, 0.20, 0.50, 0.30),
        (r"burger|המבורגר", 720, 0.25, 0.40, 0.35),
        (r"oatmeal|שיבולת|דייס", 350, 0.15, 0.65, 0.20),
        (r"yogurt|יוגורט", 180, 0.35, 0.40, 0.25),
        (r"soup|מרק", 250, 0.25, 0.45, 0.30),
        (r"fish|salmon|דג|סלמון", 520, 0.40, 0.05, 0.55),
        (r"steak|בשר", 600, 0.45, 0.05, 0.50),
        (r"apple|banana|fruit|תפוח|בננה|פרי", 95, 0.05, 0.90, 0.05),
        (r"coffee|קפה", 25, 0.10, 0.70, 0.20),
        (r"sandwich|כריך", 420, 0.25, 0.45, 0.30),
    ]
    for pattern, calories, protein_pct, carb_pct, fat_pct in rules:
        if re.search(pattern, text):
            protein, carbohydrates, fats = _macros_from_calories(
                calories, protein_pct, carb_pct, fat_pct
            )
            return CalorieEstimate(
                calories=float(calories),
                explanation="Local estimate based on typical portion size.",
                ai_estimated=False,
                protein=protein,
                carbohydrates=carbohydrates,
                fats=fats,
            )

    calories = 400.0
    protein, carbohydrates, fats = _macros_from_calories(calories)
    return CalorieEstimate(
        calories=calories,
        explanation="Local default estimate for a typical single serving.",
        ai_estimated=False,
        protein=protein,
        carbohydrates=carbohydrates,
        fats=fats,
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
        f'Estimate nutrition for this meal: "{food_name}".\n'
        f"User profile: {_user_context(user)}.\n"
        "Assume a typical single serving unless the description specifies otherwise."
    )
    try:
        return _gemini_meal_estimate(prompt)
    except Exception as exc:
        logger.warning(
            "Meal nutrition AI failed for %r, using local fallback: %s",
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
        return _gemini_calorie_estimate(prompt)
    except Exception as exc:
        logger.warning(
            "Workout calorie AI failed for %r, using local fallback: %s",
            activity_type,
            exc,
            exc_info=True,
        )
        return _fallback_workout_estimate(activity_type, user)


def calories_from_macros(protein: float, carbohydrates: float, fats: float) -> float:
    return round(protein * 4 + carbohydrates * 4 + fats * 9, 1)
