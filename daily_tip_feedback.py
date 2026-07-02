import hashlib
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from models import DailyTipFeedback, User

FeedbackAction = Literal["like", "dislike"]
FEEDBACK_PROMPT_LIMIT = 8


def tip_text_hash(tip_text: str) -> str:
    normalized = " ".join(tip_text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fetch_feedback_for_prompt(db: Session, user_id: int, language: str) -> dict[str, list[dict]]:
    liked = (
        db.query(DailyTipFeedback)
        .filter(
            DailyTipFeedback.user_id == user_id,
            DailyTipFeedback.language == language,
            DailyTipFeedback.rating == "like",
        )
        .order_by(DailyTipFeedback.updated_at.desc())
        .limit(FEEDBACK_PROMPT_LIMIT)
        .all()
    )
    disliked = (
        db.query(DailyTipFeedback)
        .filter(
            DailyTipFeedback.user_id == user_id,
            DailyTipFeedback.language == language,
            DailyTipFeedback.rating == "dislike",
        )
        .order_by(DailyTipFeedback.updated_at.desc())
        .limit(FEEDBACK_PROMPT_LIMIT)
        .all()
    )
    return {
        "liked": [{"category": row.category, "text": row.tip_text} for row in liked],
        "disliked": [{"category": row.category, "text": row.tip_text} for row in disliked],
    }


def feedback_lookup(db: Session, user_id: int, tip_texts: list[str]) -> dict[str, str]:
    if not tip_texts:
        return {}
    hashes = [tip_text_hash(text) for text in tip_texts]
    rows = (
        db.query(DailyTipFeedback)
        .filter(DailyTipFeedback.user_id == user_id, DailyTipFeedback.tip_hash.in_(hashes))
        .all()
    )
    return {row.tip_hash: row.rating for row in rows}


def attach_feedback_to_tips(db: Session, user_id: int, tips: list[dict]) -> list[dict]:
    lookup = feedback_lookup(db, user_id, [tip.get("text", "") for tip in tips])
    enriched = []
    for tip in tips:
        tip_hash = tip_text_hash(tip.get("text", ""))
        enriched.append({**tip, "feedback": lookup.get(tip_hash)})
    return enriched


def toggle_tip_feedback(
    db: Session,
    user: User,
    tip_text: str,
    category: str,
    language: str,
    action: FeedbackAction,
) -> FeedbackAction | None:
    language = "he" if language == "he" else "en"
    category = category if category in ("nutrition", "sport", "info") else "nutrition"
    tip_text = tip_text.strip()
    if not tip_text:
        raise ValueError("tip_text is required")

    tip_hash = tip_text_hash(tip_text)
    existing = (
        db.query(DailyTipFeedback)
        .filter(DailyTipFeedback.user_id == user.id, DailyTipFeedback.tip_hash == tip_hash)
        .first()
    )

    if existing and existing.rating == action:
        db.delete(existing)
        db.flush()
        return None

    if existing:
        existing.rating = action
        existing.category = category
        existing.language = language
        existing.tip_text = tip_text[:480]
        existing.updated_at = datetime.utcnow()
    else:
        db.add(
            DailyTipFeedback(
                user_id=user.id,
                tip_hash=tip_hash,
                tip_text=tip_text[:480],
                category=category,
                language=language,
                rating=action,
            )
        )
    db.flush()
    return action
