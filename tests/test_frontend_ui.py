"""Smoke tests for frontend HTML/JS contracts served by the home page."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def home_html(client: TestClient) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.text


class TestMealWorkoutListIcons:
    def test_list_icon_button_helpers_present(self, home_html: str) -> None:
        assert "function createListIconButton" in home_html
        assert "async function copyListItemText" in home_html
        assert "LIST_ICON_SVGS" in home_html
        assert 'copy: `' in home_html
        assert 'edit: `' in home_html
        assert 'delete: `' in home_html

    def test_list_icon_styles_present(self, home_html: str) -> None:
        assert ".list-icon-btn" in home_html
        assert ".list-icon-btn--danger:hover" in home_html
        assert ".list-item-icon-actions" in home_html

    def test_render_list_uses_icon_actions(self, home_html: str) -> None:
        assert 'iconActions.className = "list-item-icon-actions"' in home_html
        assert 'icon: "copy"' in home_html
        assert 'icon: "edit"' in home_html
        assert 'icon: "delete"' in home_html
        assert 'variant: "danger"' in home_html
        assert 'className = "btn-secondary list-edit-btn"' not in home_html
        assert 'className = "btn-danger list-delete-btn"' not in home_html

    def test_copy_i18n_strings(self, home_html: str) -> None:
        assert 'copyBtn: "Copy text"' in home_html
        assert 'copySuccess: "Copied to clipboard."' in home_html
        assert 'copyBtn: "העתק טקסט"' in home_html
        assert 'copySuccess: "הועתק ללוח."' in home_html

    def test_icon_buttons_use_tooltips(self, home_html: str) -> None:
        assert "button.title = label" in home_html
        assert 'button.setAttribute("aria-label", label)' in home_html


class TestWeightInputStepping:
    def test_weight_input_stepping_helpers(self, home_html: str) -> None:
        assert "const WEIGHT_INPUT_STEP = 0.1" in home_html
        assert "function formatWeightInputValue" in home_html
        assert "function adjustWeightInput" in home_html
        assert "function setupWeightInputStepping" in home_html
        assert "setupWeightInputStepping();" in home_html

    def test_weight_input_markup(self, home_html: str) -> None:
        assert 'id="weight-value-input"' in home_html
        assert 'step="0.1"' in home_html
        assert 'inputmode="decimal"' in home_html

    def test_weight_modal_formats_initial_value(self, home_html: str) -> None:
        assert "formatWeightInputValue(initialWeight)" in home_html


class TestTimezoneFrontend:
    def test_utc_logged_at_parsing_helpers(self, home_html: str) -> None:
        assert "function parseUtcLoggedAt" in home_html
        assert "function clientTzOffsetMinutes" in home_html
        assert "function summaryQueryParams" in home_html
        assert 'return new Date(`${value}Z`)' in home_html

    def test_summary_and_dates_pass_tz_offset(self, home_html: str) -> None:
        assert "tz_offset=${clientTzOffsetMinutes()}" in home_html
        assert "summaryQueryParams(selectedDate)" in home_html
        assert "summaryQueryParams(iso)" in home_html

    def test_local_time_display_uses_utc_parser(self, home_html: str) -> None:
        assert "parseUtcLoggedAt(isoString)" in home_html
        assert "parseUtcLoggedAt(data.logged_at)" in home_html


class TestDefaultTipsFrontend:
    def test_daily_tips_need_data_message(self, home_html: str) -> None:
        assert "dailyTipsNeedData" in home_html
        assert "personalized" in home_html
