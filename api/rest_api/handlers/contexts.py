"""Context document request handlers."""

import logging
from typing import Dict, Any
from ..services import ContextService
from ..utils import success_response, error_response, parse_body

logger = logging.getLogger(__name__)


class ContextHandlers:
    """Handles context document HTTP requests."""

    def __init__(self, context_service: ContextService):
        self.context_service = context_service

    def create_context(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle POST /contexts."""
        try:
            body = parse_body(event)
            name = body.get("name", "").strip()
            if not name:
                return error_response(400, "Missing required field: name")
            description = body.get("description", "").strip()

            claims = (
                event.get("requestContext", {})
                .get("authorizer", {})
                .get("jwt", {})
                .get("claims", {})
            )
            created_by = claims.get("sub", "")

            result = self.context_service.create_context(name, description, created_by=created_by)
            return success_response(result, status_code=201)
        except Exception as e:
            logger.error(f"Error creating context: {str(e)}")
            return error_response(500, "Failed to create context")

    def list_contexts(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /contexts."""
        try:
            result = self.context_service.list_contexts()
            return success_response(result)
        except Exception as e:
            logger.error(f"Error listing contexts: {str(e)}")
            return error_response(500, "Failed to list contexts")

    def get_context(self, context_id: str, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /contexts/{id}."""
        try:
            result = self.context_service.get_context(context_id)
            if not result:
                return error_response(404, f"Context not found: {context_id}")
            return success_response(result)
        except Exception as e:
            logger.error(f"Error getting context: {str(e)}")
            return error_response(500, "Failed to get context")

    def delete_context(
        self, context_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle DELETE /contexts/{id}."""
        try:
            result = self.context_service.delete_context(context_id)
            if not result:
                return error_response(404, f"Context not found: {context_id}")
            return success_response(result)
        except Exception as e:
            logger.error(f"Error deleting context: {str(e)}")
            return error_response(500, "Failed to delete context")

    def get_context_content(
        self, context_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle GET /contexts/{id}/content."""
        try:
            content = self.context_service.get_context_content(context_id)
            if content is None:
                return error_response(404, f"Context not found: {context_id}")
            return success_response({"context_id": context_id, "content": content})
        except Exception as e:
            logger.error(f"Error getting context content: {str(e)}")
            return error_response(500, "Failed to get context content")

    def update_context_content(
        self, context_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle PUT /contexts/{id}/content."""
        try:
            body = parse_body(event)
            content = body.get("content", "")
            if not content:
                return error_response(400, "Missing required field: content")
            result = self.context_service.update_context_content(context_id, content)
            if not result:
                return error_response(404, f"Context not found: {context_id}")
            return success_response(result)
        except Exception as e:
            logger.error(f"Error updating context content: {str(e)}")
            return error_response(500, "Failed to update context content")
