"""Project request handlers."""
import logging
from typing import Dict, Any
from ..services import ProjectService
from ..utils import success_response, error_response, parse_body, get_user_identity, get_user_role, UserRole

logger = logging.getLogger(__name__)


class ProjectHandlers:
    """Handles project-related HTTP requests."""

    def __init__(self, project_service: ProjectService):
        """Initialise project handlers.

        Args:
            project_service: Project service instance.
        """
        self.project_service = project_service

    def create_project(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle POST /projects — create a new project.

        Viewers are not permitted to create projects.

        Args:
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
            body = parse_body(event)

            name = body.get('name', '').strip()
            if not name:
                return error_response(400, 'Missing required field: name')

            description = body.get('description', '').strip()
            context_id = body.get('context_id', '')
            files = body.get('files') or None

            result = self.project_service.create_project(
                name, description, created_by=user_sub,
                created_by_email=user_email,
                context_id=context_id, files=files,
            )

            return success_response(result, status_code=201)

        except ValueError as e:
            return error_response(400, str(e))
        except Exception as e:
            logger.error(f"Error creating project: {e}", exc_info=True)
            return error_response(500, 'Failed to create project')

    def list_projects(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /projects — list projects.

        Admins and viewers see all projects (GSI1). Users see only their
        own projects (GSI2).

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
            query_params = event.get('queryStringParameters') or {}
            status_filter = query_params.get('status')
            limit = int(query_params.get('limit', 50))

            if role == UserRole.USER:
                result = self.project_service.list_projects_for_user(user_sub, limit)
            else:
                # Admins and viewers see all projects
                result = self.project_service.list_projects(status_filter, limit)

            return success_response(result)

        except Exception as e:
            logger.error(f"Error listing projects: {e}", exc_info=True)
            return error_response(500, 'Failed to list projects')

    def get_project(self, project_id: str, event: Dict[str, Any],
                    context: Any) -> Dict[str, Any]:
        """Handle GET /projects/{id} — get project details.

        Users may only access their own projects. Admins and viewers can
        access any project.

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
            # Only regular users are restricted to their own projects
            if role == UserRole.USER:
                try:
                    self.project_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f'Project not found: {project_id}')
                except PermissionError:
                    return error_response(403, 'Access denied')

            # Single response path — includes review data for all roles
            result = self.project_service.get_project(project_id)
            if not result:
                return error_response(404, f'Project not found: {project_id}')

            return success_response(result)

        except Exception as e:
            logger.error(f"Error getting project: {e}", exc_info=True)
            return error_response(500, 'Failed to get project')

    def get_project_document(self, project_id: str, event: Dict[str, Any],
                             context: Any) -> Dict[str, Any]:
        """Handle GET /projects/{id}/document — get uploaded document content.

        Users may only access their own projects. Admins and viewers can
        access any project.

        Args:
            project_id: Project identifier.
            event: API Gateway event.
            context: Lambda context.

        Returns:
            API Gateway response with document text content.
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

            result = self.project_service.get_project_document(project_id)

            if result is None:
                return error_response(404, f'Project not found: {project_id}')
            if result.get('error'):
                return error_response(404, result['error'])

            return success_response(result)

        except Exception as e:
            logger.error(f"Error getting project document: {e}", exc_info=True)
            return error_response(500, 'Failed to get project document')

    def delete_project(self, project_id: str, event: Dict[str, Any],
                       context: Any) -> Dict[str, Any]:
        """Handle DELETE /projects/{id} — delete a project.

        Viewers cannot delete projects. Non-admins may only delete their
        own projects.

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

            result = self.project_service.delete_project(project_id)

            if not result:
                return error_response(404, f'Project not found: {project_id}')

            return success_response(result)

        except Exception as e:
            logger.error(f"Error deleting project: {e}", exc_info=True)
            return error_response(500, 'Failed to delete project')
