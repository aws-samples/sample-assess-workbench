"""Feedback request handlers."""
import logging
from typing import Dict, Any
from ..services.feedback_service import FeedbackService
from ..services.project_service import ProjectService
from ..utils import success_response, error_response, parse_body, get_user_identity, get_user_role, UserRole

logger = logging.getLogger(__name__)


class FeedbackHandlers:
    """Handles feedback-related HTTP requests."""

    def __init__(self, feedback_service: FeedbackService, project_service: ProjectService):
        """Initialise feedback handlers.

        Args:
            feedback_service: Feedback service instance.
            project_service: Project service instance (for ownership checks).
        """
        self.feedback_service = feedback_service
        self.project_service = project_service

    def submit_feedback(self, project_id: str, event: Dict[str, Any],
                        context: Any) -> Dict[str, Any]:
        """Handle POST /projects/{id}/feedback.

        Viewers cannot submit feedback. Non-admins may only submit feedback
        on their own projects.

        Args:
            project_id: Project identifier.
            event: API Gateway event.
            context: Lambda context.

        Returns:
            API Gateway response.
        """
        try:
            role = get_user_role(event)
            user_sub, user_email = get_user_identity(event)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(401, str(e))

        if role == UserRole.VIEWER:
            return error_response(403, 'Viewers have read-only access')

        try:
            if role != UserRole.ADMIN:
                try:
                    self.project_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f'Project not found: {project_id}')
                except PermissionError:
                    return error_response(403, 'Access denied')

            body = parse_body(event)

            finding_id = (body.get('finding_id') or '').strip()
            agent_type = (body.get('agent_type') or '').strip()
            value = (body.get('value') or '').strip()

            if not finding_id:
                return error_response(400, 'Missing required field: finding_id')
            if not agent_type:
                return error_response(400, 'Missing required field: agent_type')
            if value not in ('up', 'down'):
                return error_response(400, 'value must be "up" or "down"')

            # Prefer email for human-readable feedback attribution; fall back to sub.
            user = user_email or user_sub

            result = self.feedback_service.submit_feedback(
                project_id, finding_id, agent_type, value, user,
            )
            return success_response(result, status_code=201)

        except Exception as e:
            logger.error(f"Error submitting feedback: {e}", exc_info=True)
            return error_response(500, 'Failed to submit feedback')

    def get_feedback(self, project_id: str, event: Dict[str, Any],
                     context: Any) -> Dict[str, Any]:
        """Handle GET /projects/{id}/feedback.

        Users may only access feedback for their own projects. Admins and
        viewers can access any project's feedback.

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
                    self.project_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f'Project not found: {project_id}')
                except PermissionError:
                    return error_response(403, 'Access denied')

            result = self.feedback_service.get_project_feedback(project_id)
            return success_response(result)

        except Exception as e:
            logger.error(f"Error getting feedback: {e}", exc_info=True)
            return error_response(500, 'Failed to get feedback')
