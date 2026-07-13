import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta

import google.generativeai as genai
from sqlalchemy import func
from sqlalchemy.orm import Session

from gemini_insight import GEMINI_MODEL, GEMINI_MODEL_FALLBACKS, _user_profile_text
from daily_tip_feedback import attach_feedback_to_tips, fetch_feedback_for_prompt
from default_daily_tips import DEFAULT_TIP_COUNT, build_default_daily_tips
from models import DailySteps, DailyTipsCache, DailyWeight, Meal, User, Workout

logger = logging.getLogger(__name__)

TIP_COUNT = DEFAULT_TIP_COUNT
PREVIEW_WORDS = 10
MIN_TIP_CHARS = 80
MAX_TIP_CHARS = 480


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(target_date, time.min), datetime.combine(target_date, time.max)


def _default_context_end_date() -> date:
    """Most recent complete day for tips — excludes today (often still in progress)."""
    return date.today() - timedelta(days=1)


def fetch_three_day_context(db: Session, user: User, end_date: date | None = None) -> dict:
    end_date = end_date or _default_context_end_date()
    days = [end_date - timedelta(days=offset) for offset in range(2, -1, -1)]

    daily_records = []
    for day in days:
        day_start, day_end = _day_bounds(day)

        calories_consumed = float(
            db.query(func.coalesce(func.sum(Meal.calories), 0.0))
            .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
            .scalar()
        )
        total_protein = float(
            db.query(func.coalesce(func.sum(Meal.protein), 0.0))
            .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
            .scalar()
        )
        total_carbs = float(
            db.query(func.coalesce(func.sum(Meal.carbohydrates), 0.0))
            .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
            .scalar()
        )
        total_fats = float(
            db.query(func.coalesce(func.sum(Meal.fats), 0.0))
            .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
            .scalar()
        )
        calories_burned = float(
            db.query(func.coalesce(func.sum(Workout.calories_burned), 0.0))
            .filter(Workout.user_id == user.id, Workout.logged_at >= day_start, Workout.logged_at <= day_end)
            .scalar()
        )

        meals = (
            db.query(Meal)
            .filter(Meal.user_id == user.id, Meal.logged_at >= day_start, Meal.logged_at <= day_end)
            .order_by(Meal.logged_at.asc())
            .all()
        )
        workouts = (
            db.query(Workout)
            .filter(Workout.user_id == user.id, Workout.logged_at >= day_start, Workout.logged_at <= day_end)
            .order_by(Workout.logged_at.asc())
            .all()
        )
        steps = (
            db.query(DailySteps)
            .filter(DailySteps.user_id == user.id, DailySteps.entry_date == day)
            .first()
        )
        weight = (
            db.query(DailyWeight)
            .filter(DailyWeight.user_id == user.id, DailyWeight.entry_date == day)
            .first()
        )

        daily_records.append(
            {
                "date": day.isoformat(),
                "calories_consumed": calories_consumed,
                "total_protein": total_protein,
                "total_carbohydrates": total_carbs,
                "total_fats": total_fats,
                "calories_burned": calories_burned,
                "steps_count": steps.steps_count if steps else None,
                "steps_calories_burned": float(steps.calories_burned) if steps else 0.0,
                "weight_kg": weight.weight_kg if weight else None,
                "meals": [
                    {
                        "food_name": meal.food_name,
                        "calories": meal.calories,
                        "protein": meal.protein,
                        "carbohydrates": meal.carbohydrates,
                        "fats": meal.fats,
                    }
                    for meal in meals
                ],
                "workouts": [
                    {
                        "activity_type": workout.activity_type,
                        "calories_burned": workout.calories_burned,
                    }
                    for workout in workouts
                ],
            }
        )

    return {
        "end_date": end_date.isoformat(),
        "days": daily_records,
        "profile": {
            "name": user.name,
            "gender": user.gender,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "height_cm": user.height_cm,
            "weight_kg": user.weight_kg,
            "bmr": user.bmr,
        },
    }


def _context_has_tracking_data(context: dict) -> bool:
    for day in context.get("days") or []:
        if day.get("meals") or day.get("workouts"):
            return True
        if day.get("steps_count") is not None:
            return True
        if day.get("weight_kg") is not None:
            return True
    return False


def _default_daily_tips(user: User, language: str) -> list[dict]:
    """Onboarding plus random starter tips when the user has no recent logged data."""
    return build_default_daily_tips(user, language)


def _build_tips_prompt(
    user: User,
    context: dict,
    language: str,
    feedback: dict | None = None,
) -> str:
    language_instruction = "Respond in Hebrew." if language == "he" else "Respond in English."
    feedback = feedback or {"liked": [], "disliked": []}

    day_blocks = []
    for day in context["days"]:
        meal_lines = [
            (
                f"  - {meal['food_name']} ({meal['calories']:.0f} cal, "
                f"{meal['protein']:.0f}g protein, {meal['carbohydrates']:.0f}g carbs, {meal['fats']:.0f}g fats)"
            )
            for meal in day["meals"]
        ] or ["  - No meals logged"]
        workout_lines = [
            f"  - {workout['activity_type']} ({workout['calories_burned']:.0f} cal burned)"
            for workout in day["workouts"]
        ] or ["  - No workouts logged"]
        steps_line = (
            f"Steps: {day['steps_count']} ({day['steps_calories_burned']:.0f} cal)"
            if day["steps_count"] is not None
            else "Steps: not logged"
        )
        weight_line = (
            f"Weight: {day['weight_kg']:.1f} kg" if day["weight_kg"] is not None else "Weight: not logged"
        )
        day_blocks.append(
            f"Date: {day['date']}\n"
            f"Calories consumed: {day['calories_consumed']:.0f}\n"
            f"Protein: {day['total_protein']:.0f}g | Carbs: {day['total_carbohydrates']:.0f}g | Fats: {day['total_fats']:.0f}g\n"
            f"Exercise burned: {day['calories_burned']:.0f}\n"
            f"{steps_line}\n"
            f"{weight_line}\n"
            f"Meals:\n{chr(10).join(meal_lines)}\n"
            f"Workouts:\n{chr(10).join(workout_lines)}"
        )

    feedback_blocks = []
    if feedback.get("liked"):
        liked_lines = "\n".join(
            f"- [{item['category']}] {item['text']}" for item in feedback["liked"]
        )
        feedback_blocks.append(
            "Tips the user LIKED (expand on this style, specificity, and depth — similar tone and data references):\n"
            f"{liked_lines}"
        )
    if feedback.get("disliked"):
        disliked_lines = "\n".join(
            f"- [{item['category']}] {item['text']}" for item in feedback["disliked"]
        )
        feedback_blocks.append(
            "Tips the user DISLIKED (avoid similar topics, vagueness, or tone — narrow away from these patterns):\n"
            f"{disliked_lines}"
        )
    feedback_section = (
        "\n\nUser feedback on past tips:\n" + "\n\n".join(feedback_blocks)
        if feedback_blocks
        else ""
    )

    return f"""You are a supportive nutrition and fitness coach who writes highly personalized advice.

Create exactly {TIP_COUNT} practical tips for this specific user based ONLY on their profile and the last 3 complete days of tracked data below (exclude today — it is often incomplete).

Requirements for EVERY tip:
- Write 2-3 full sentences ({MIN_TIP_CHARS}-{MAX_TIP_CHARS} characters total).
- Reference concrete details from the logs: exact food names, workout types, dates, step counts, weights, calories, protein, or BMR.
- Compare trends across the 3 days when relevant (e.g. protein dropped, steps increased, missing workouts).
- Give a specific next action tied to their data — not generic wellness advice.
- Mix nutrition and sport/activity tips (about half and half).
- Do NOT repeat the same suggestion twice.

{language_instruction}

User profile: {_user_profile_text(user)}
BMR: {user.bmr or "unknown"}

Last 3 complete days of tracked data (excluding today):
{chr(10).join(day_blocks)}
{feedback_section}

Return JSON only with this exact shape:
{{"tips": [{{"category": "nutrition", "text": "..."}}, {{"category": "sport", "text": "..."}}]}}
"""


def _parse_tips_json(text: str) -> list[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    tips = data.get("tips") or []
    parsed = []
    for index, item in enumerate(tips):
        category = str(item.get("category", "")).strip().lower()
        if category not in ("nutrition", "sport"):
            category = "nutrition" if index % 2 == 0 else "sport"
        text_value = str(item.get("text", "")).strip()
        if not text_value:
            continue
        parsed.append({"category": category, "text": text_value[:MAX_TIP_CHARS]})
    if len(parsed) < 4:
        raise ValueError("Too few tips returned")
    return parsed[:TIP_COUNT]


def _append_tip(tips: list[dict], category: str, text: str) -> None:
    if text and len(tips) < TIP_COUNT:
        tips.append({"category": category, "text": text[:MAX_TIP_CHARS]})


def _fallback_daily_tips(context: dict, language: str) -> list[dict]:
    days = context["days"]
    profile = context["profile"]
    tips: list[dict] = []
    name = profile.get("name") or ("שלך" if language == "he" else "your")
    bmr = profile.get("bmr")

    all_meals: list[tuple[str, dict]] = []
    all_workouts: list[tuple[str, dict]] = []
    for day in days:
        for meal in day.get("meals") or []:
            all_meals.append((day["date"], meal))
        for workout in day.get("workouts") or []:
            all_workouts.append((day["date"], workout))

    latest_day = days[-1] if days else {}
    previous_day = days[-2] if len(days) > 1 else {}
    protein_latest = float(latest_day.get("total_protein") or 0)
    protein_previous = float(previous_day.get("total_protein") or 0)
    consumed_latest = float(latest_day.get("calories_consumed") or 0)
    steps_latest = latest_day.get("steps_count")
    steps_previous = previous_day.get("steps_count")
    latest_date = latest_day.get("date", "")
    previous_date = previous_day.get("date", "")

    if language == "he":
        if all_meals:
            meal_date, meal = all_meals[-1]
            _append_tip(
                tips,
                "nutrition",
                (
                    f"ב-{meal_date} רשמת {meal['food_name']} ({meal['calories']:.0f} קלוריות, "
                    f"{meal['protein']:.0f}ג חלבון). נסה/י לשלב ירק או סלט בצד בארוחה הבאה כדי להגדיל נפח "
                    f"וסיבים בלי הרבה קלוריות נוספות."
                ),
            )
        if protein_latest > 0 and protein_latest < 70:
            _append_tip(
                tips,
                "nutrition",
                (
                    f"ב-{latest_date} צרכת {protein_latest:.0f}ג חלבון"
                    f"{f' לעומת {protein_previous:.0f}ג ב-{previous_date}' if protein_previous else ''}. "
                    f"הוסף/י מנה חלבונית ממוקדת — ביצים, יוגורט יווני או טופו — בארוחה הבאה כדי לתמוך בשובע ושיקום."
                ),
            )
        if bmr and consumed_latest:
            balance = consumed_latest - float(bmr)
            if balance > 250:
                _append_tip(
                    tips,
                    "nutrition",
                    (
                        f"ב-{latest_date} צרכת {consumed_latest:.0f} קלוריות, מעל BMR שלך ({bmr:.0f}). "
                        f"אם המטרה היא איזון, שקול/י ארוחת ערב קלה יותר עם חלבון וירקות, "
                        f"במיוחד אחרי יום עם פחות פעילות."
                    ),
                )
            elif balance < -300:
                _append_tip(
                    tips,
                    "nutrition",
                    (
                        f"ב-{latest_date} צרכת {consumed_latest:.0f} קלוריות לעומת BMR {bmr:.0f} — פער של כ-{abs(balance):.0f} קלוריות. "
                        f"ודא/י ארוחה מספקת עם חלבון ופחמימות מורכבות כדי לא להישאר בגרעון חריג."
                    ),
                )
        if all_workouts:
            workout_date, workout = all_workouts[-1]
            _append_tip(
                tips,
                "sport",
                (
                    f"האימון האחרון שרשמת: {workout['activity_type']} ב-{workout_date} "
                    f"({workout['calories_burned']:.0f} קלוריות). הוסף/י 5–10 דקות מתיחות ביום שאחרי "
                    f"כדי לשפר התאוששות ולהפחית כאיבים."
                ),
            )
        elif not (latest_day.get("workouts") or []):
            _append_tip(
                tips,
                "sport",
                (
                    f"לא נרשמו אימונים ב-{latest_date or 'היום האחרון ברישום'}. "
                    f"נסה/י הליכה מהירה 20–30 דקות היום — זה ישלים את הצעדים ויעזור לאיזון הקלורי."
                ),
            )
        if steps_latest is not None:
            trend = ""
            if steps_previous is not None and steps_previous > 0:
                change = ((steps_latest - steps_previous) / steps_previous) * 100
                trend = f" ({change:+.0f}% לעומת {steps_previous:,} ב-{previous_date})"
            _append_tip(
                tips,
                "sport",
                (
                    f"רשמת {steps_latest:,} צעדים ב-{latest_date}{trend}. "
                    f"{'שמור/י על הקצב — זה תומך בירידה/שמירה על משקל בריא.' if steps_latest >= 7000 else 'נסה/י להוסיף 2–3 הליכות קצרות של 10 דקות במהלך היום.'}"
                ),
            )
        weights = [(day["date"], day["weight_kg"]) for day in days if day.get("weight_kg") is not None]
        if len(weights) >= 2:
            first_date, first_weight = weights[0]
            last_date, last_weight = weights[-1]
            delta = last_weight - first_weight
            _append_tip(
                tips,
                "nutrition",
                (
                    f"המשקל שלך עלה/ירד מ-{first_weight:.1f} ק\"ג ב-{first_date} ל-{last_weight:.1f} ק\"ג ב-{last_date} "
                    f"({delta:+.1f} ק\"ג). התאם/י את גודל המנות והחלבון בהתאם למגמה שאת/ה רוצה לשמור."
                ),
            )
        meal_names = [meal["food_name"] for _, meal in all_meals[-3:]]
        if meal_names:
            _append_tip(
                tips,
                "nutrition",
                (
                    f"בימים האחרונים רשמת בעיקר: {', '.join(meal_names)}. "
                    f"גוון/י במקורות חלבון וירקות בימים הקרובים כדי לכסות מגוון רחב יותר של מיקרוניוטריאנטים."
                ),
            )
        if not all_meals:
            _append_tip(
                tips,
                "nutrition",
                (
                    f"אין ארוחות רשומות ב-3 הימים האחרונים. התחל/י ב-{name} עם ארוחה אחת פשוטה היום — "
                    f"רישום עקבי הוא הבסיס לטיפים מדויקים יותר."
                ),
            )
    else:
        if all_meals:
            meal_date, meal = all_meals[-1]
            _append_tip(
                tips,
                "nutrition",
                (
                    f"On {meal_date} you logged {meal['food_name']} ({meal['calories']:.0f} cal, "
                    f"{meal['protein']:.0f}g protein). Pair your next similar meal with vegetables or salad "
                    f"to add volume and fiber without many extra calories."
                ),
            )
        if protein_latest > 0 and protein_latest < 70:
            _append_tip(
                tips,
                "nutrition",
                (
                    f"On {latest_date}, protein was {protein_latest:.0f}g"
                    f"{f' vs {protein_previous:.0f}g on {previous_date}' if protein_previous else ''}. "
                    f"Add a focused protein serving — eggs, Greek yogurt, or tofu — at your next meal "
                    f"to support recovery and satiety."
                ),
            )
        if bmr and consumed_latest:
            balance = consumed_latest - float(bmr)
            if balance > 250:
                _append_tip(
                    tips,
                    "nutrition",
                    (
                        f"On {latest_date}, you consumed {consumed_latest:.0f} cal, above your BMR of {bmr:.0f}. "
                        f"If balance is your goal, plan a lighter dinner with lean protein and vegetables, "
                        f"especially after a lower-activity day."
                    ),
                )
            elif balance < -300:
                _append_tip(
                    tips,
                    "nutrition",
                    (
                        f"On {latest_date}, you logged {consumed_latest:.0f} cal vs a {bmr:.0f} BMR — about {abs(balance):.0f} cal below baseline. "
                        f"Include a substantial meal with protein and complex carbs so the deficit stays healthy."
                    ),
                )
        if all_workouts:
            workout_date, workout = all_workouts[-1]
            _append_tip(
                tips,
                "sport",
                (
                    f"Your latest workout was {workout['activity_type']} on {workout_date} "
                    f"({workout['calories_burned']:.0f} cal burned). Add 5–10 minutes of stretching the next day "
                    f"to improve recovery and reduce soreness."
                ),
            )
        elif not (latest_day.get("workouts") or []):
            _append_tip(
                tips,
                "sport",
                (
                    f"No workouts were logged on {latest_date or 'your most recent tracked day'}. "
                    f"Try a brisk 20–30 minute walk today to complement your steps and calorie balance."
                ),
            )
        if steps_latest is not None:
            trend = ""
            if steps_previous is not None and steps_previous > 0:
                change = ((steps_latest - steps_previous) / steps_previous) * 100
                trend = f" ({change:+.0f}% vs {steps_previous:,} on {previous_date})"
            _append_tip(
                tips,
                "sport",
                (
                    f"You logged {steps_latest:,} steps on {latest_date}{trend}. "
                    f"{'Keep this pace — it supports healthy weight maintenance.' if steps_latest >= 7000 else 'Add 2–3 short 10-minute walks to build your daily total.'}"
                ),
            )
        weights = [(day["date"], day["weight_kg"]) for day in days if day.get("weight_kg") is not None]
        if len(weights) >= 2:
            first_date, first_weight = weights[0]
            last_date, last_weight = weights[-1]
            delta = last_weight - first_weight
            _append_tip(
                tips,
                "nutrition",
                (
                    f"Your weight moved from {first_weight:.1f} kg on {first_date} to {last_weight:.1f} kg on {last_date} "
                    f"({delta:+.1f} kg). Adjust portion sizes and protein intake to match the trend you want."
                ),
            )
        meal_names = [meal["food_name"] for _, meal in all_meals[-3:]]
        if meal_names:
            _append_tip(
                tips,
                "nutrition",
                (
                    f"Recent meals include: {', '.join(meal_names)}. "
                    f"Vary protein sources and vegetables over the next few days to broaden micronutrient coverage."
                ),
            )
        if not all_meals:
            _append_tip(
                tips,
                "nutrition",
                (
                    f"No meals were logged in the last 3 days. Start with one simple meal today — "
                    f"consistent tracking unlocks much more specific tips for you."
                ),
            )

    generic_fillers_he = [
        ("nutrition", "עקוב/י אחרי שתייה לאורך היום, במיוחד בימים עם יותר צעדים או אימונים שרשמת."),
        ("sport", "תכנן/י מראש מתי תתאמן/ת — רישום עקבי של אימונים עוזר לזהות מה באמת עובד עבורך."),
        ("nutrition", "כשאת/ה מוסיף/ה ארוחה חדשה, רשום/ה אותה מיד — כך הטיפים הבאים יתבססו על נתונים עדכניים."),
        ("sport", "שלב/י יום מנוחה פעילה עם הליכה קלה בין אימונים קשים שכבר מופיעים ברישום שלך."),
    ]
    generic_fillers_en = [
        ("nutrition", "Track hydration on days with higher step counts or logged workouts."),
        ("sport", "Schedule workouts in advance — consistent logging reveals what works for you."),
        ("nutrition", "Log new meals right away so future tips reflect your latest data."),
        ("sport", "Use active recovery walks between harder sessions already in your log."),
    ]
    fillers = generic_fillers_he if language == "he" else generic_fillers_en
    filler_index = 0
    while len(tips) < TIP_COUNT:
        category, text = fillers[filler_index % len(fillers)]
        _append_tip(tips, category, text)
        filler_index += 1

    return tips[:TIP_COUNT]


def _generate_tips_with_ai(
    user: User,
    context: dict,
    language: str,
    api_key: str | None,
    db: Session | None = None,
) -> tuple[list[dict], str, bool]:
    if not _context_has_tracking_data(context):
        return _default_daily_tips(user, language), "general-no-data", False

    feedback = fetch_feedback_for_prompt(db, user.id, language) if db else {"liked": [], "disliked": []}

    if not api_key:
        return _fallback_daily_tips(context, language), "local-fallback", False

    prompt = _build_tips_prompt(user, context, language, feedback)
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
                tips = _parse_tips_json(response.text or "")
                logger.info("Gemini daily tips succeeded with model %s for %s", model_name, user.username)
                return tips, model_name, True
            except Exception as exc:
                logger.warning("Gemini daily tips model %s failed: %s", model_name, exc)
                last_error = exc
                continue
        raise last_error or RuntimeError("No Gemini model available")
    except Exception as exc:
        logger.warning(
            "Daily tips AI failed for %s, using local fallback: %s",
            user.username,
            exc,
            exc_info=True,
        )
        return _fallback_daily_tips(context, language), "local-fallback", False


def _serialize_tips(tips: list[dict]) -> list[dict]:
    return [
        {
            "id": index + 1,
            "category": tip["category"],
            "text": tip["text"],
            "preview": _preview_text(tip["text"]),
        }
        for index, tip in enumerate(tips)
    ]


def _preview_text(text: str, word_count: int = PREVIEW_WORDS) -> str:
    words = text.split()
    if len(words) <= word_count:
        return text
    return " ".join(words[:word_count]) + "…"


def get_cached_daily_tips(
    db: Session,
    user: User,
    tip_date: date,
    language: str,
) -> DailyTipsCache | None:
    return (
        db.query(DailyTipsCache)
        .filter(
            DailyTipsCache.user_id == user.id,
            DailyTipsCache.tip_date == tip_date,
            DailyTipsCache.language == language,
        )
        .first()
    )


def get_or_create_daily_tips(
    user: User,
    db: Session,
    language: str = "en",
    force_refresh: bool = False,
    api_key: str | None = None,
) -> dict:
    language = "he" if language == "he" else "en"
    tip_date = date.today()
    cached = get_cached_daily_tips(db, user, tip_date, language)

    if cached and not force_refresh and cached.model != "general-no-data":
        tips = attach_feedback_to_tips(db, user.id, json.loads(cached.tips_json))
        return {
            "tip_date": tip_date.isoformat(),
            "language": language,
            "tips": tips,
            "cached": True,
            "personalized": cached.model != "general-no-data",
            "ai_estimated": cached.ai_estimated,
            "model": cached.model,
        }

    context = fetch_three_day_context(db, user)
    has_tracking_data = _context_has_tracking_data(context)
    tips_raw, model_name, ai_estimated = _generate_tips_with_ai(user, context, language, api_key, db)
    serialized = _serialize_tips(tips_raw)
    tips = attach_feedback_to_tips(db, user.id, serialized)

    if model_name == "general-no-data":
        return {
            "tip_date": tip_date.isoformat(),
            "language": language,
            "tips": tips,
            "cached": False,
            "personalized": False,
            "ai_estimated": ai_estimated,
            "model": model_name,
        }

    payload = json.dumps(serialized, ensure_ascii=False)

    if cached:
        cached.tips_json = payload
        cached.ai_estimated = ai_estimated
        cached.model = model_name
        cached.created_at = datetime.utcnow()
    else:
        db.add(
            DailyTipsCache(
                user_id=user.id,
                tip_date=tip_date,
                language=language,
                tips_json=payload,
                ai_estimated=ai_estimated,
                model=model_name,
            )
        )

    db.flush()
    return {
        "tip_date": tip_date.isoformat(),
        "language": language,
        "tips": tips,
        "cached": False,
        "personalized": has_tracking_data,
        "ai_estimated": ai_estimated,
        "model": model_name,
    }
