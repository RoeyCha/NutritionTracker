"""Default onboarding and starter tips for users without enough tracked data."""

from __future__ import annotations

import random

from bmr_calculator import _profile_ready, resolve_height_cm
from models import User
from profile_utils import profile_height_cm, user_age_for_calculations

ONBOARDING_TIP_COUNT = 6
RANDOM_TIP_SELECT_COUNT = 6
DEFAULT_TIP_COUNT = ONBOARDING_TIP_COUNT + RANDOM_TIP_SELECT_COUNT

ONBOARDING_TIP_IDS = tuple(range(1, ONBOARDING_TIP_COUNT + 1))
RANDOM_TIP_IDS = tuple(range(ONBOARDING_TIP_COUNT + 1, 21))


def _gender_label(language: str, gender: str | None) -> str:
    if language == "he":
        labels = {"male": "גבר", "female": "אישה", "other": "אחר"}
        return labels.get(gender or "", "לא צוין")
    labels = {"male": "male", "female": "female", "other": "other"}
    return labels.get(gender or "", "not specified")


def _missing_profile_fields(user: User) -> list[str]:
    missing: list[str] = []
    if user.birth_date is None:
        missing.append("birth_date")
    if user.weight_kg is None:
        missing.append("weight_kg")
    if user.height_cm is None:
        missing.append("height_cm")
    if not user.gender:
        missing.append("gender")
    return missing


def _missing_profile_message(language: str, missing: list[str], *, context: str) -> str:
    if language == "he":
        labels = {
            "birth_date": "תאריך לידה",
            "weight_kg": "משקל (ק\"ג)",
            "height_cm": "גובה (ס\"מ)",
            "gender": "מגדר",
        }
        fields = ", ".join(labels[field] for field in missing if field in labels)
        return (
            f"{context} "
            f"הוסף/י {fields} תחת **עריכת פרופיל** כדי לפתוח חישובי BMR, יתרה יומית וטיפים מדויקים יותר."
        ).replace("**עריכת פרופיל**", "עריכת פרופיל")

    labels = {
        "birth_date": "birth date",
        "weight_kg": "weight (kg)",
        "height_cm": "height (cm)",
        "gender": "gender",
    }
    fields = ", ".join(labels[field] for field in missing if field in labels)
    return (
        f"{context} "
        f"Add your {fields} under Edit profile to unlock BMR, daily balance, and more accurate tips."
    )


def _onboarding_templates(language: str) -> dict[int, tuple[str, str]]:
    if language == "he":
        return {
            1: (
                "info",
                "ברוכ/ה הבא/ה ל-Nutrition Tracker, {name}! אלה טיפים להתחלה בזמן שאת/ה בונה את הרישום. "
                "הוסף/י ארוחות, אימונים, צעדים ומשקל במשך מספר ימים — "
                "וטיפים מותאמים אישית מ-AI יופיעו כאן אוטומטית.",
            ),
            2: (
                "info",
                "התחל/י בפשטות: רשום/י ארוחה ראשונה ב«הוסף ארוחה». "
                "הקלד/י מה אכלת (למשל \"2 ביצים וטוסט\") — קלוריות ומאקרו מחושבים אוטומטית ב-AI. "
                "אפשר לערוך את השעה אם אכלת מוקדם יותר היום.",
            ),
            3: (
                "info",
                "רשום/י פעילות תחת «הוסף אימון» — ריצה, חדר כושר או אפילו הליכה. "
                "האפליקציה מעריכה קלוריות שנשרפו כדי שהיתרה היומית תישאר מדויקת.",
            ),
            4: (
                "info",
                "הקש/י על עיפרון ליד «קלוריות מצעדים» בסיכום היומי כדי להזין את מספר הצעדים לאותו יום. "
                "צעדים נספרים ב«סה״כ יצא» יחד עם BMR ופעילות.",
            ),
            5: (
                "info",
                "רשום/י משקל מהסיכום היומי (עיפרון ליד משקל). "
                "מעקב משקל לאורך זמן עוזר לראות מגמות בלשונית «סטטוס שבועי».",
            ),
            6: (
                "info",
                "השתמש/י בלוח השנה מעל הסיכום כדי לקפוץ בין ימים עם נתונים. "
                "רק תאריכי עבר עם ארוחות, אימונים או צעדים ניתנים לבחירה — תאריכי עתיד חסומים.",
            ),
        }

    return {
        1: (
            "info",
            "Welcome to Nutrition Tracker, {name}! These are starter tips while you build your log. "
            "Add meals, workouts, steps, and weight over the next few days — "
            "personalized AI tips will appear here automatically once there is enough data.",
        ),
        2: (
            "info",
            "Start simple: log your first meal using Add Meal. "
            "Type what you ate (e.g. \"2 eggs and toast\") — calories and macros are estimated automatically by AI. "
            "You can edit the time if you ate earlier today.",
        ),
        3: (
            "info",
            "Log activities under Add Workout — a run, gym session, or even a walk. "
            "The app estimates calories burned so your daily balance stays accurate.",
        ),
        4: (
            "info",
            "Tap the pencil icon next to Steps burned in the daily summary to enter your step count for that day. "
            "Steps count toward your total calories out, alongside BMR and exercise.",
        ),
        5: (
            "info",
            "Log your weight from the daily summary (pencil icon next to Weight). "
            "Tracking weight over time helps you see trends in the Weekly Status tab.",
        ),
        6: (
            "info",
            "Use the calendar above the summary to jump between days that have logged data. "
            "Only past dates with meals, workouts, or steps can be selected — future dates stay disabled.",
        ),
    }


def _resolve_random_tip(user: User, tip_id: int, language: str) -> tuple[str, str]:
    name = user.name or ("שלך" if language == "he" else "there")
    missing = _missing_profile_fields(user)
    bmr_ready = _profile_ready(user) and user.bmr is not None
    age = user_age_for_calculations(user)
    height = profile_height_cm(user) or resolve_height_cm(user)
    weight = float(user.weight_kg) if user.weight_kg is not None else None
    gender = _gender_label(language, user.gender)

    if language == "he":
        return _resolve_random_tip_he(
            user,
            tip_id,
            name=name,
            missing=missing,
            bmr_ready=bmr_ready,
            age=age,
            height=height,
            weight=weight,
            gender=gender,
        )
    return _resolve_random_tip_en(
        user,
        tip_id,
        name=name,
        missing=missing,
        bmr_ready=bmr_ready,
        age=age,
        height=height,
        weight=weight,
        gender=gender,
    )


def _resolve_random_tip_en(
    user: User,
    tip_id: int,
    *,
    name: str,
    missing: list[str],
    bmr_ready: bool,
    age: int | None,
    height: float,
    weight: float | None,
    gender: str,
) -> tuple[str, str]:
    if tip_id == 7:
        return (
            "info",
            "Open the Weekly Status tab to see charts for calories, weight, steps, and macros over 5 days, "
            "a week, a month, or longer. It is the best way to spot patterns once you have logged a few days.",
        )
    if tip_id == 8:
        return (
            "info",
            "Tap any tip in this bar to read the full message. Use the like or dislike buttons to tell the app "
            "what you find helpful — future tips will adapt to your preferences.",
        )
    if tip_id == 9:
        return (
            "info",
            "Your profile menu (top right) lets you edit your details, export or import your data, and refresh daily tips. "
            "Export is useful if you want a backup of your nutrition history.",
        )
    if tip_id == 10:
        return (
            "info",
            "Consistency beats perfection. Even one meal and one activity logged today gives tomorrow's summary "
            "something to work with — and unlocks much smarter tips after about three days of tracking.",
        )
    if tip_id == 11:
        if not bmr_ready:
            need = [field for field in ("birth_date", "weight_kg") if field in missing]
            return (
                "nutrition",
                _missing_profile_message(
                    "en",
                    need or missing,
                    context="Your profile powers BMR and daily balance.",
                ),
            )
        height_note = (
            f"{height:.0f} cm"
            if user.height_cm is not None
            else f"{height:.0f} cm (typical estimate — add height for a precise BMR)"
        )
        return (
            "nutrition",
            f"Your profile shows you are {age} years old, {height_note}, and {weight:.1f} kg ({gender}). "
            f"The app uses this to estimate your BMR (basal metabolic rate): about {user.bmr:.0f} kcal/day, "
            f"the energy your body burns at rest.",
        )
    if tip_id == 12:
        return (
            "nutrition",
            "Daily balance compares calories you eat to calories you burn. "
            "Total out includes your BMR plus exercise and steps. "
            "A negative balance means you burned more than you consumed that day; a positive balance means the opposite.",
        )
    if tip_id == 13:
        return (
            "nutrition",
            "Aim for a balanced plate over the day: enough protein for muscle and satiety, "
            "carbs for energy, and fats for hormones and fullness. "
            "Once you log meals, protein, carbs, and fats appear in your daily summary totals.",
        )
    if tip_id == 14:
        if not bmr_ready:
            need = [field for field in ("birth_date", "weight_kg") if field in missing]
            return (
                "nutrition",
                _missing_profile_message(
                    "en",
                    need or missing,
                    context="Calorie goals start from your personal BMR.",
                ),
            )
        return (
            "nutrition",
            f"For steady, healthy weight management, many adults aim near maintenance — eating roughly what they burn "
            f"(BMR plus activity) — or a modest deficit below total out. "
            f"Your BMR of about {user.bmr:.0f} kcal is the baseline; activity adds on top.",
        )
    if tip_id == 15:
        if not bmr_ready:
            return (
                "nutrition",
                _missing_profile_message(
                    "en",
                    [field for field in ("birth_date", "weight_kg") if field in missing] or missing,
                    context="If BMR or daily balance shows \"Complete your profile\",",
                ),
            )
        return (
            "nutrition",
            f"Your BMR ({user.bmr:.0f} kcal/day) is now calculated from your profile and shown in the daily summary. "
            f"Use it as your baseline when reading daily balance and total calories out.",
        )
    if tip_id == 16:
        return (
            "info",
            "Made a mistake? Tap Edit on any meal or workout in the daily list to change the name, time, or details. "
            "Use Delete if you logged something by accident — your summary updates right away.",
        )
    if tip_id == 17:
        return (
            "info",
            "Logged the same food before? If you enter a similar meal name again, the app reuses your previous "
            "calorie and macro estimate — no new AI call needed. Consistent naming (e.g. always \"Greek yogurt bowl\") "
            "makes tracking faster.",
        )
    if tip_id == 18:
        return (
            "info",
            "Set the correct date and time when logging — especially for late-night meals or morning workouts. "
            "The summary groups entries by day based on when they happened, not when you typed them.",
        )
    if tip_id == 19:
        return (
            "info",
            "Use Refresh summary after adding entries if totals look stale. "
            "The calendar only enables dates that already have meals, workouts, or steps — "
            "so each log helps you navigate your history.",
        )
    if tip_id == 20:
        if weight is None:
            return (
                "nutrition",
                _missing_profile_message(
                    "en",
                    ["weight_kg"],
                    context="Good nutrition is not only about calories.",
                ),
            )
        return (
            "nutrition",
            "Good nutrition is not only about calories. Once you log a few meals, check protein (g) in the daily summary — "
            "including a solid protein source at each main meal supports muscle, recovery, and lasting fullness.",
        )

    raise ValueError(f"Unknown random tip id: {tip_id}")


def _resolve_random_tip_he(
    user: User,
    tip_id: int,
    *,
    name: str,
    missing: list[str],
    bmr_ready: bool,
    age: int | None,
    height: float,
    weight: float | None,
    gender: str,
) -> tuple[str, str]:
    if tip_id == 7:
        return (
            "info",
            "פתח/י את לשונית «סטטוס שבועי» כדי לראות גרפים של קלוריות, משקל, צעדים ומאקרו ל-5 ימים, שבוע, חודש ויותר. "
            "זו הדרך הטובה ביותר לזהות דפוסים אחרי כמה ימי רישום.",
        )
    if tip_id == 8:
        return (
            "info",
            "הקש/י על כל טיפ בפס הזה לקריאה מלאה. השתמש/י בלייק או דיסלייק כדי לסמן מה עוזר לך — "
            "טיפים עתידיים יתאימו את עצמם להעדפות שלך.",
        )
    if tip_id == 9:
        return (
            "info",
            "תפריט הפרופיל (למעלה מימין) מאפשר עריכת פרטים, ייצוא/ייבוא נתונים ורענון טיפים יומיים. "
            "ייצוא שימושי לגיבוי של היסטוריית התזונה שלך.",
        )
    if tip_id == 10:
        return (
            "info",
            "עקביות חשובה ממושלמות. גם ארוחה אחת ופעילות אחת היום נותנים לסיכום של מחר מה לעבוד איתו — "
            "ואחרי כשלושה ימי מעקב יופיעו כאן טיפים חכמים בהרבה.",
        )
    if tip_id == 11:
        if not bmr_ready:
            need = [field for field in ("birth_date", "weight_kg") if field in missing]
            return (
                "nutrition",
                _missing_profile_message(
                    "he",
                    need or missing,
                    context="הפרופיל שלך מפעיל BMR ויתרה יומית.",
                ),
            )
        height_note = (
            f"{height:.0f} ס\"מ"
            if user.height_cm is not None
            else f"{height:.0f} ס\"מ (הערכה טיפוסית — הוסף/י גובה ל-BMR מדויק יותר)"
        )
        return (
            "nutrition",
            f"הפרופיל שלך מראה שאת/ה בן/בת {age}, {height_note}, {weight:.1f} ק\"ג ({gender}). "
            f"האפליקציה משתמשת בזה לחישוב BMR (קצב חילוף חומרים בסיסי): כ-{user.bmr:.0f} קלוריות ליום "
            f"— האנרגיה שהגוף שורף במנוחה.",
        )
    if tip_id == 12:
        return (
            "nutrition",
            "«יתרה יומית» משווה קלוריות שנאכלו לקלוריות שנשרפו. "
            "«סה״כ יצא» כולל BMR, אימונים וצעדים. "
            "יתרה שלילית = שרפת יותר מאשר צרכת; יתרה חיובית = להפך.",
        )
    if tip_id == 13:
        return (
            "nutrition",
            "כוון/י לצלחת מאוזנת לאורך היום: מספיק חלבון לשובע ושרירים, "
            "פחמימות לאנרגיה ושומנים לספיגת ויטמינים ולשובע. "
            "אחרי רישום ארוחות, חלבון, פחמימות ושומנים מופיעים בסיכום היומי.",
        )
    if tip_id == 14:
        if not bmr_ready:
            need = [field for field in ("birth_date", "weight_kg") if field in missing]
            return (
                "nutrition",
                _missing_profile_message(
                    "he",
                    need or missing,
                    context="יעדי קלוריות מתחילים מה-BMR האישי שלך.",
                ),
            )
        return (
            "nutrition",
            f"לניהול משקל בריא, רבים שומרים ליד תחזוקה — אכילה בערך כמו השריפה (BMR + פעילות) "
            f"או גירעון מתון מתחת ל«סה״כ יצא». "
            f"ה-BMR שלך (~{user.bmr:.0f} קלוריות) הוא הבסיס; פעילות מוסיפה מעל.",
        )
    if tip_id == 15:
        if not bmr_ready:
            return (
                "nutrition",
                _missing_profile_message(
                    "he",
                    [field for field in ("birth_date", "weight_kg") if field in missing] or missing,
                    context="אם BMR או יתרה יומית מציגים \"השלם/י פרופיל\",",
                ),
            )
        return (
            "nutrition",
            f"ה-BMR שלך ({user.bmr:.0f} קלוריות ליום) מחושב מהפרופיל ומוצג בסיכום היומי. "
            f"השתמש/י בו כבסיס כשקורא/ת «יתרה יומית» ו«סה״כ יצא».",
        )
    if tip_id == 16:
        return (
            "info",
            "טעית? הקש/י «ערוך» על ארוחה או אימון ברשימה כדי לשנות שם, שעה או פרטים. "
            "השתמש/י ב«מחק» אם נרשם בטעות — הסיכום מתעדכן מיד.",
        )
    if tip_id == 17:
        return (
            "info",
            "אכלת את אותו מאכל בעבר? שם ארוחה דומה ממחזר את הערכת הקלוריות והמאקרו הקודמת — "
            "בלי קריאת AI חדשה. שמות עקביים (למשל תמיד \"קערת יוגורט יווני\") מזרזים רישום.",
        )
    if tip_id == 18:
        return (
            "info",
            "הגדר/י תאריך ושעה נכונים בעת רישום — במיוחד לארוחות לילה או אימוני בוקר. "
            "הסיכום מקבץ לפי מתי זה קרה, לא מתי הקלדת.",
        )
    if tip_id == 19:
        return (
            "info",
            "השתמש/י ב«רענון סיכום» אחרי הוספת רשומות אם הסכומים נראים ישנים. "
            "לוח השנה מאפשר רק תאריכים שכבר יש בהם ארוחות, אימונים או צעדים — כל רישום עוזר לניווט.",
        )
    if tip_id == 20:
        if weight is None:
            return (
                "nutrition",
                _missing_profile_message(
                    "he",
                    ["weight_kg"],
                    context="תזונה טובה היא לא רק קלוריות.",
                ),
            )
        return (
            "nutrition",
            "תזונה טובה היא לא רק קלוריות. אחרי כמה ארוחות רשומות, בדוק/י חלבון (ג) בסיכום היומי — "
            "מקור חלבון משמעותי בכל ארוחה עיקרית תומך בשרירים, התאוששות ושובע לאורך זמן.",
        )

    raise ValueError(f"Unknown random tip id: {tip_id}")


def build_default_daily_tips(
    user: User,
    language: str,
    rng: random.Random | None = None,
) -> list[dict]:
    """Return 6 fixed onboarding tips plus 6 random tips from the starter pool."""
    language = "he" if language == "he" else "en"
    rng = rng or random.Random()
    display_name = user.name or ("חבר/ה" if language == "he" else "there")

    onboarding = _onboarding_templates(language)
    tips: list[dict] = []
    for tip_id in ONBOARDING_TIP_IDS:
        category, text = onboarding[tip_id]
        if tip_id == 1:
            text = text.format(name=display_name)
        tips.append({"category": category, "text": text})

    selected_ids = rng.sample(list(RANDOM_TIP_IDS), RANDOM_TIP_SELECT_COUNT)
    for tip_id in selected_ids:
        category, text = _resolve_random_tip(user, tip_id, language)
        tips.append({"category": category, "text": text})

    return tips
