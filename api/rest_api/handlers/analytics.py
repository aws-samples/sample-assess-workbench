"""Analytics request handlers."""

import logging
from typing import Dict, Any
from ..services.analytics_service import AnalyticsService
from ..utils import success_response, error_response, get_user_identity, get_user_role, UserRole

logger = logging.getLogger(__name__)


class AnalyticsHandlers:
    """Handles analytics-related HTTP requests."""

    def __init__(self, analytics_service: AnalyticsService):
        self.analytics_service = analytics_service

    def get_summary(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /analytics/summary.

        Admins and viewers receive aggregate analytics across all projects
        (viewer is a full-read role). Users receive analytics scoped to their
        own projects.

        Args:
            event: API Gateway event.
            context: Lambda context.

        Returns:
            API Gateway response.
        """
        try:
            role = get_user_role(event)
            user_sub, _ = get_user_identity(event)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(401, str(e))

        try:
            scoped_sub = "" if role in (UserRole.ADMIN, UserRole.VIEWER) else user_sub
            result = self.analytics_service.get_summary(user_sub=scoped_sub)
            return success_response(result)
        except Exception as e:
            logger.error(f"Error getting analytics summary: {e}", exc_info=True)
            return error_response(500, "Failed to get analytics summary")

    def get_trends(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /analytics/trends.

        Admins and viewers receive aggregate trends across all projects
        (viewer is a full-read role). Users receive trends scoped to their
        own projects.

        Args:
            event: API Gateway event.
            context: Lambda context.

        Returns:
            API Gateway response.
        """
        try:
            role = get_user_role(event)
            user_sub, _ = get_user_identity(event)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(401, str(e))

        try:
            qs = event.get("queryStringParameters") or {}
            agent_type = qs.get("agent") or None
            limit = int(qs.get("limit", "30"))
            scoped_sub = "" if role in (UserRole.ADMIN, UserRole.VIEWER) else user_sub
            result = self.analytics_service.get_trends(
                agent_type=agent_type,
                limit=limit,
                user_sub=scoped_sub,
            )
            return success_response(result)
        except Exception as e:
            logger.error(f"Error getting analytics trends: {e}", exc_info=True)
            return error_response(500, "Failed to get analytics trends")

    def get_coverage(self, project_id: str, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /analytics/coverage/{project_id}.

        Users may only access coverage for their own projects. Admins and
        viewers can access any project's coverage.

        Args:
            project_id: Project identifier.
            event: API Gateway event.
            context: Lambda context.

        Returns:
            API Gateway response.
        """
        try:
            role = get_user_role(event)
            user_sub, _ = get_user_identity(event)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(401, str(e))

        try:
            if role == UserRole.USER:
                try:
                    self.analytics_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            result = self.analytics_service.get_coverage(project_id)
            return success_response(result)
        except ValueError as e:
            return error_response(404, str(e))
        except Exception as e:
            logger.error(f"Error getting coverage: {e}", exc_info=True)
            return error_response(500, "Failed to get coverage data")
