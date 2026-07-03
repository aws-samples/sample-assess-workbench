"""Unit tests for AnalyticsHandlers role scoping.

Contract: admins and viewers receive aggregate analytics across all projects
(viewer is a full-read role), so the handler passes user_sub="" to the service.
Users receive analytics scoped to their own projects (user_sub=<their sub>).
"""

from unittest.mock import MagicMock

from rest_api.handlers.analytics import AnalyticsHandlers
from rest_api.utils.auth import ADMIN_GROUP, USER_GROUP, VIEWER_GROUP


def _event(sub: str, groups: str) -> dict:
    return {
        "requestContext": {
            "authorizer": {
                "jwt": {"claims": {"sub": sub, "email": "u@example.com", "cognito:groups": groups}}
            }
        }
    }


def _handlers() -> tuple[AnalyticsHandlers, MagicMock]:
    service = MagicMock()
    service.get_summary.return_value = {"review_count": 0}
    service.get_trends.return_value = {"data_points": [], "count": 0}
    return AnalyticsHandlers(service), service


class TestAnalyticsSummaryScoping:
    def test_admin_gets_all_projects(self) -> None:
        handlers, service = _handlers()
        handlers.get_summary(_event("admin-1", ADMIN_GROUP), None)
        service.get_summary.assert_called_once_with(user_sub="")

    def test_viewer_gets_all_projects(self) -> None:
        handlers, service = _handlers()
        handlers.get_summary(_event("viewer-1", VIEWER_GROUP), None)
        service.get_summary.assert_called_once_with(user_sub="")

    def test_user_is_scoped_to_own(self) -> None:
        handlers, service = _handlers()
        handlers.get_summary(_event("user-1", USER_GROUP), None)
        service.get_summary.assert_called_once_with(user_sub="user-1")


class TestAnalyticsTrendsScoping:
    def test_admin_gets_all_projects(self) -> None:
        handlers, service = _handlers()
        handlers.get_trends(_event("admin-1", ADMIN_GROUP), None)
        assert service.get_trends.call_args.kwargs["user_sub"] == ""

    def test_viewer_gets_all_projects(self) -> None:
        handlers, service = _handlers()
        handlers.get_trends(_event("viewer-1", VIEWER_GROUP), None)
        assert service.get_trends.call_args.kwargs["user_sub"] == ""

    def test_user_is_scoped_to_own(self) -> None:
        handlers, service = _handlers()
        handlers.get_trends(_event("user-1", USER_GROUP), None)
        assert service.get_trends.call_args.kwargs["user_sub"] == "user-1"
