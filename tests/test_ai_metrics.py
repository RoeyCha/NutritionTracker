from datetime import datetime, timedelta

from ai_metrics import build_ai_metrics
from models import AiCallLog


def test_build_ai_metrics_aggregates_calls(empty_client) -> None:
    db = empty_client.db_session
    now = datetime.utcnow()
    db.add_all(
        [
            AiCallLog(
                feature="daily_tips",
                model="gemini-test",
                success=True,
                request_bytes=100,
                response_bytes=200,
                created_at=now - timedelta(days=1),
            ),
            AiCallLog(
                feature="meal_calories",
                model="gemini-test",
                success=False,
                error_message="timeout",
                request_bytes=50,
                response_bytes=0,
                created_at=now - timedelta(days=1),
            ),
        ]
    )
    db.commit()

    metrics = build_ai_metrics(db, days=7)
    assert metrics["totals"]["total_calls"] == 2
    assert metrics["totals"]["success_calls"] == 1
    assert metrics["totals"]["failure_calls"] == 1
    assert metrics["totals"]["request_bytes"] == 150
    assert metrics["totals"]["response_bytes"] == 200
    assert len(metrics["daily"]) == 1
    assert metrics["daily"][0]["total_calls"] == 2
