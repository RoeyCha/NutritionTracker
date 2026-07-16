"""Smoke tests for admin dashboard HTML/JS contracts."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def admin_html(empty_client: TestClient) -> str:
    response = empty_client.get("/admin")
    assert response.status_code == 200
    return response.text


@pytest.fixture()
def home_html(client: TestClient) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.text


class TestAdminDashboardUi:
    def test_admin_page_has_dashboard_sections(self, admin_html: str) -> None:
        assert "Admin Dashboard" in admin_html
        assert "Gemini API Key" in admin_html
        assert "Site backup" in admin_html
        assert 'id="users-table-body"' in admin_html

    def test_admin_page_uses_activity_modal_not_inline_log(self, admin_html: str) -> None:
        assert 'id="activity-modal"' in admin_html
        assert "Auth activity log" not in admin_html
        assert "openActivityModal" in admin_html
        assert 'action: "view-activity"' in admin_html

    def test_admin_page_has_toast_feedback(self, admin_html: str) -> None:
        assert 'id="toast-host"' in admin_html
        assert "function showToast" in admin_html
        assert "function showActionFeedback" in admin_html
        assert "Password reset for" in admin_html

    def test_admin_user_actions_use_icon_buttons(self, admin_html: str) -> None:
        assert "ADMIN_ICON_SVGS" in admin_html
        assert '"reset-password"' in admin_html
        assert "function adminIconButtonHtml" in admin_html
        assert ".list-icon-btn" in admin_html
        assert "Open app" not in admin_html

    def test_admin_redirects_unauthenticated_users_to_login(self, admin_html: str) -> None:
        assert "redirectToLogin" in admin_html
        assert 'window.location.replace("/")' in admin_html


class TestMainAppAdminRedirect:
    def test_login_redirects_admin_users(self, home_html: str) -> None:
        assert "data.user.is_admin" in home_html
        assert 'window.location.href = "/admin"' in home_html

    def test_meals_and_workouts_sorted_oldest_first(self, home_html: str) -> None:
        assert "function sortLoggedItems" in home_html
        assert "sortLoggedItems(items).forEach" in home_html
