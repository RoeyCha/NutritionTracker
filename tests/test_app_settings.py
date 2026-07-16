import app_settings
from app_settings import (
    GEMINI_API_KEY_SETTING,
    gemini_api_key_status,
    get_gemini_api_key,
    load_settings_from_db,
    mask_secret,
    set_gemini_api_key,
)
from models import AppSetting


def test_mask_secret_hides_middle(empty_client) -> None:
    assert mask_secret("abcdefghij") == "******ghij"
    assert mask_secret("abc") == "****"
    assert mask_secret(None) is None


def test_set_and_load_gemini_api_key(empty_client, monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app_settings._runtime_gemini_api_key = None

    db = empty_client.db_session
    set_gemini_api_key(db, "  test-api-key-value  ")
    db.commit()

    assert get_gemini_api_key() == "test-api-key-value"

    app_settings._runtime_gemini_api_key = None
    load_settings_from_db(db)
    assert get_gemini_api_key() == "test-api-key-value"

    status = gemini_api_key_status(db)
    assert status["configured"] is True
    assert status["source"] == "database"
    assert status["masked_key"] == mask_secret("test-api-key-value")

    row = db.get(AppSetting, GEMINI_API_KEY_SETTING)
    assert row is not None
    assert row.value == "test-api-key-value"
