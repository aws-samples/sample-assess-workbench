"""Admin request handlers — protected by Cognito admin group."""

import logging
from typing import Dict, Any
from ..services.admin_service import AdminService
from ..utils import success_response, error_response, parse_body, get_user_role, UserRole, can_read_admin_views

logger = logging.getLogger(__name__)


def _is_admin(event: Dict[str, Any]) -> bool:
    """Check if the caller belongs to the admin Cognito group.

    Args:
        event: API Gateway event with JWT authorizer context.

    Returns:
        True if the user has the admin role, False otherwise.
    """
    try:
        return get_user_role(event) == UserRole.ADMIN
    except PermissionError:
        return False


class AdminHandlers:
    """Handles admin-related HTTP requests."""

    def __init__(self, admin_service: AdminService):
        self.admin_service = admin_service

    def list_agents(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /agents — public endpoint."""
        try:
            result = self.admin_service.list_agents()
            return success_response(result)
        except Exception as e:
            logger.error(f"Error listing agents: {e}")
            return error_response(500, 'Failed to list agents')

    def list_models(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /models — public endpoint."""
        try:
            result = self.admin_service.list_models()
            return success_response(result)
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return error_response(500, 'Failed to list models')

    def list_registry(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /admin/registry — readable by admins and viewers."""
        if not can_read_admin_views(event):
            return error_response(403, 'Admin access required')
        try:
            result = self.admin_service.list_registry()
            return success_response(result)
        except Exception as e:
            logger.error(f"Error listing registry: {e}")
            return error_response(500, 'Failed to list registry')

    def update_registry(self, agent_type: str, event: Dict[str, Any],
                        context: Any) -> Dict[str, Any]:
        """Handle PUT /admin/registry/{agent_type}"""
        if not _is_admin(event):
            return error_response(403, 'Admin access required')
        try:
            body = parse_body(event)
            result = self.admin_service.update_registry(agent_type, body)
            return success_response(result)
        except ValueError as e:
            return error_response(400, str(e))
        except Exception as e:
            logger.error(f"Error updating registry: {e}")
            return error_response(500, 'Failed to update registry')

    def get_guardrail_events(self, event: Dict[str, Any],
                             context: Any) -> Dict[str, Any]:
        """Handle GET /admin/guardrail-events — readable by admins and viewers.

        Note: this exposes user emails. Allowed for viewers because viewers are
        trusted demo stakeholders (full-read role); see can_read_admin_views.
        """
        if not can_read_admin_views(event):
            return error_response(403, 'Admin access required')
        try:
            qs = event.get('queryStringParameters') or {}
            result = self.admin_service.get_guardrail_events(
                start_date=qs.get('start_date') or None,
                end_date=qs.get('end_date') or None,
                project_id=qs.get('project_id') or None,
                limit=int(qs.get('limit', '100')),
            )
            return success_response(result)
        except ValueError as e:
            return error_response(400, str(e))
        except Exception as e:
            logger.error(f"Error listing guardrail events: {e}")
            return error_response(500, 'Failed to list guardrail events')
