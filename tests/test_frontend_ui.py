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
        assert "min-height: 48px" in home_html
        assert ".stat-edit-btn" in home_html

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


class TestConfirmModalAndCalendarUx:
    def test_in_app_confirm_modal_present(self, home_html: str) -> None:
        assert 'id="confirm-modal"' in home_html
        assert "function askConfirm" in home_html
        assert "function closeConfirmModal" in home_html
        assert "await askConfirm" in home_html

    def test_no_native_alert_calls(self, home_html: str) -> None:
        assert "alert(" not in home_html

    def test_calendar_allows_empty_past_days(self, home_html: str) -> None:
        assert 'button.className = hasData ? "cal-day has-data" : "cal-day no-data"' in home_html
        assert "button.disabled = isFuture;" in home_html
        assert "button.disabled = isFuture || !hasData" not in home_html
        assert "Any past or today date can be selected" in home_html

    def test_weight_save_shows_toast_and_saving_label(self, home_html: str) -> None:
        assert 'showToast(t("weightSaved"))' in home_html
        assert 'weightSubmitButton.textContent = t("savingBtn")' in home_html


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
        assert "dailyTipsPrereqTitle" in home_html
        assert "showDailyTipsPrereqModal" in home_html
        assert "prerequisites_met" in home_html


class TestMediumPriorityUx:
    def test_daily_tip_modal_has_close_button(self, home_html: str) -> None:
        assert 'id="daily-tip-modal-close"' in home_html
        assert "dailyTipModalClose" in home_html
        assert "beginModalSession(dailyTipModal, dailyTipModalClose)" in home_html

    def test_daily_tips_prereq_modal_has_ctas(self, home_html: str) -> None:
        assert 'id="daily-tips-prereq-goto-yesterday"' in home_html
        assert 'id="daily-tips-prereq-refresh"' in home_html
        assert "goToDailyTipsPrereqDate" in home_html
        assert "refreshDailyTipsFromPrereqModal" in home_html
        assert "Reset & get new tips" in home_html
        assert "refresh the page" not in home_html.lower()

    def test_import_modal_autofocus_and_loading(self, home_html: str) -> None:
        assert "beginModalSession(importModal, overwriteRadio)" in home_html
        assert 'importingBtn: "Importing..."' in home_html
        assert 'setSubmitLoading(importConfirmBtn, true, "importConfirmBtn", "importingBtn")' in home_html

    def test_edit_success_shows_toast(self, home_html: str) -> None:
        assert 'showToast(t("updatedSuccess"))' in home_html

    def test_modal_focus_trap_helpers(self, home_html: str) -> None:
        assert "function beginModalSession" in home_html
        assert "function endModalSession" in home_html
        assert "function installFocusTrap" in home_html

    def test_date_time_snap_hint(self, home_html: str) -> None:
        assert "dateTimeSnapHint" in home_html
        assert "15-minute intervals" in home_html

    def test_weekly_nav_and_chart_states(self, home_html: str) -> None:
        assert "function updateWeeklyWeekNavButtons" in home_html
        assert 'toggleAttribute("disabled", atCurrentWeek)' in home_html
        assert "function setChartStatus" in home_html
        assert 'id="chart-calories-status"' in home_html
        assert "weeklyChartLoading" in home_html

    def test_dashboard_tabs_aria_and_keyboard(self, home_html: str) -> None:
        assert 'id="dashboard-tab-daily"' in home_html
        assert 'aria-controls="daily-view"' in home_html
        assert 'role="tabpanel"' in home_html
        assert "handleDashboardTabKeydown" in home_html
        assert 'tab.setAttribute("tabindex"' in home_html


class TestLowPriorityUx:
    def test_auth_autofocus_on_show_and_tab_switch(self, home_html: str) -> None:
        assert "function focusAuthPrimaryField" in home_html
        assert "focusAuthPrimaryField();" in home_html

    def test_register_form_password_confirm_and_optional_details(self, home_html: str) -> None:
        assert 'id="register-password-confirm"' in home_html
        assert "passwordConfirm" in home_html
        assert "passwordMismatch" in home_html
        assert 'class="register-optional"' in home_html
        assert "registerOptionalDetails" in home_html
        assert home_html.index('id="register-password"') < home_html.index('class="register-optional"')

    def test_calorie_modal_only_when_ai_explanation(self, home_html: str) -> None:
        assert "if (data.ai_explanation)" in home_html
        assert "data.calories_recalculated || !isEdit" not in home_html

    def test_daily_tips_and_calendar_touch_targets(self, home_html: str) -> None:
        assert ".daily-tips-nav" in home_html
        assert "min-width: 48px" in home_html
        assert ".daily-tip-feedback-btn" in home_html
        assert "min-height: 2.75rem" in home_html

    def test_localized_aria_labels(self, home_html: str) -> None:
        assert 'data-i18n-aria-label="calPrevMonth"' in home_html
        assert 'data-i18n-aria-label="dashboardViewsLabel"' in home_html
        assert 'data-i18n-aria-label="chartCaloriesAria"' in home_html
        assert '${t("calPrevMonth")}' in home_html
