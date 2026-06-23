import json
import logging
import os
import re
from dataclasses import dataclass

import google.generativeai as genai

from gemini_insight import GEMINI_MODEL, GEMINI_MODEL_FALLBACKS
from models import User
from profile_utils import user_age_for_calculations

logger = logging.getLogger(__name__)


@dataclass
class StepsCalorieEstimate:
    calories_burned: float
    explanation: str
    ai_estimated: bool


def _user_context(user: User) -> str:
    parts = []
    if user.birth_date is not None:
        age = user_age_for_calculations(user)
        if age is not None:
            parts.append(f"age {age}")
    if user.height_cm is not None:
        parts.append(f"height {user.height_cm} cm")
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


def _format_workouts(workouts: list[dict]) -> str:
    if not workouts:
        return "None logged."
    lines = [
        f"- {item['activity_type']}: {item['calories_burned']} cal already counted"
        for item in workouts
    ]
    return "\n".join(lines)


def _step_overlap_calories(workouts: list[dict]) -> float:
    overlap = 0.0
    for item in workouts:
        activity = item["activity_type"].lower()
        if re.search(r"walk|run|hike|jog|step|הליכ|ריצ|טיול", activity):
            overlap += float(item["calories_burned"])
    return overlap


def _fallback_steps_calories(
    user: User, steps_count: int, workouts: list[dict]
) -> StepsCalorieEstimate:
    weight = user.weight_kg or 70.0
    gross = round(steps_count * 0.04 * (weight / 70.0), 1)
    overlap = round(_step_overlap_calories(workouts), 1)
    net = max(0.0, round(gross - overlap, 1))

    explanation_parts = [
        f"{steps_count:,} steps at {weight:g} kg → about {gross:g} kcal estimated walking burn."
    ]
    if overlap > 0:
        explanation_parts.append(
            f"Subtracted {overlap:g} kcal already counted in walking/running workouts to avoid double-counting."
        )
    explanation_parts.append(f"Net steps contribution: {net:g} kcal. Calculated locally — no AI.")

    return StepsCalorieEstimate(
        calories_burned=net,
        explanation=" ".join(explanation_parts),
        ai_estimated=False,
    )


def _gemini_steps_calories(
    user: User, steps_count: int, workouts: list[dict]
) -> StepsCalorieEstimate:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    prompt = (
        f"User profile: {_user_context(user)}.\n"
        f"Total daily steps: {steps_count} (includes all steps for the day, including during logged workouts).\n\n"
        f"Workouts already logged today (their calories are counted separately):\n"
        f"{_format_workouts(workouts)}\n\n"
        "Estimate ONLY the additional calories burned from daily steps that are NOT already "
        "represented by the logged workouts above. Walking and running workouts overlap with "
        "step count — do not double-count them.\n"
        "Respond with JSON only using keys: calories_burned (number), explanation (string). "
        "calories_burned must be >= 0 with at most one decimal place."
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
            response = model.generate_content(prompt)
            data = _extract_json(response.text or "{}")
            calories = float(data["calories_burned"])
            if calories < 0:
                raise ValueError("calories_burned must be non-negative")
            logger.info("Gemini steps estimate succeeded with model %s", model_name)
            return StepsCalorieEstimate(
                calories_burned=round(calories, 1),
                explanation=str(data.get("explanation", "")).strip(),
                ai_estimated=True,
            )
        except Exception as exc:
            logger.warning("Gemini steps model %s failed: %s", model_name, exc)
            last_error = exc
            continue
    raise last_error or RuntimeError("No Gemini model available")


def estimate_steps_calories(
    user: User, steps_count: int, workouts: list[dict]
) -> StepsCalorieEstimate:
    """Estimate net step calories locally (no AI).

    Walking/running workout calories logged the same day are subtracted to avoid double-counting.
    """
    return _fallback_steps_calories(user, steps_count, workouts)
