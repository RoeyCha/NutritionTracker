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
class BmrEstimate:
    bmr: float
    explanation: str
    ai_estimated: bool


def _profile_ready(user: User) -> bool:
    return user.age is not None and user.weight_kg is not None


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _fallback_bmr(user: User) -> BmrEstimate:
    weight = float(user.weight_kg)
    age = int(user.age)
    height_cm = {"male": 175.0, "female": 162.0}.get(user.gender or "", 170.0)

    if user.gender == "female":
        bmr = 10 * weight + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * weight + 6.25 * height_cm - 5 * age + 5

    bmr = round(max(bmr, 800.0), 1)
    return BmrEstimate(
        bmr=bmr,
        explanation="Local estimate using Mifflin-St Jeor with typical height for your profile.",
        ai_estimated=False,
    )


def _gemini_bmr(user: User) -> BmrEstimate:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    gender = user.gender or "not specified"
    prompt = (
        f"Estimate BMR (Basal Metabolic Rate) in calories per day for this person:\n"
        f"- Gender: {gender}\n"
        f"- Age: {user.age} years\n"
        f"- Weight: {user.weight_kg} kg\n\n"
        "Use established formulas where height is unknown (assume a typical height for the profile). "
        "Respond with JSON only using keys: bmr (number), explanation (string). "
        "bmr must be a positive number with at most one decimal place."
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
            bmr = float(data["bmr"])
            if bmr <= 0:
                raise ValueError("BMR must be positive")
            logger.info("Gemini BMR estimate succeeded with model %s", model_name)
            return BmrEstimate(
                bmr=round(bmr, 1),
                explanation=str(data.get("explanation", "")).strip(),
                ai_estimated=True,
            )
        except Exception as exc:
            logger.warning("Gemini BMR model %s failed: %s", model_name, exc)
            last_error = exc
            continue
    raise last_error or RuntimeError("No Gemini model available")


def calculate_user_bmr(user: User) -> BmrEstimate | None:
    if not _profile_ready(user):
        return None

    try:
        return _gemini_bmr(user)
    except Exception as exc:
        logger.warning(
            "BMR AI failed for user %s, using local fallback: %s",
            user.username,
            exc,
            exc_info=True,
        )
        return _fallback_bmr(user)


def apply_bmr_to_user(user: User) -> bool:
    estimate = calculate_user_bmr(user)
    if estimate is None:
        user.bmr = None
        user.bmr_explanation = None
        return False

    user.bmr = estimate.bmr
    user.bmr_explanation = estimate.explanation
    return True
