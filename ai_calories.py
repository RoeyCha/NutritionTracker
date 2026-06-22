import json
import os
import re
from dataclasses import dataclass

from fastapi import HTTPException, status

from models import User

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


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


def _openai_estimate(prompt: str) -> CalorieEstimate:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is not installed") from exc

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You estimate calories for nutrition tracking. "
                    "Respond with JSON only using keys: calories (number), explanation (string). "
                    "Calories must be a positive number with at most one decimal place."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = _extract_json(content)
    calories = float(data["calories"])
    if calories <= 0:
        raise ValueError("Calories must be positive")
    return CalorieEstimate(
        calories=round(calories, 1),
        explanation=str(data.get("explanation", "")).strip(),
        ai_estimated=True,
    )


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
        return _openai_estimate(prompt)
    except Exception:
        if os.getenv("OPENAI_API_KEY"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI calorie estimation is temporarily unavailable. Try again shortly.",
            )
        return _fallback_meal_estimate(food_name)


def estimate_workout_calories(activity_type: str, user: User) -> CalorieEstimate:
    prompt = (
        f'Estimate calories burned for this activity: "{activity_type}".\n'
        f"User profile: {_user_context(user)}.\n"
        "If duration is not specified, assume a moderate 30-minute session."
    )
    try:
        return _openai_estimate(prompt)
    except Exception:
        if os.getenv("OPENAI_API_KEY"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI calorie estimation is temporarily unavailable. Try again shortly.",
            )
        return _fallback_workout_estimate(activity_type, user)
