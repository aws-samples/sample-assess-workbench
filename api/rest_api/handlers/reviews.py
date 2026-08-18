"""Review request handlers."""

import logging
from typing import Dict, Any
from ..data_access import ConflictError
from ..services import ReviewService
from ..utils import success_response, error_response, get_user_identity, get_user_role, UserRole

logger = logging.getLogger(__name__)


class ReviewHandlers:
    """Handles review-related HTTP requests."""

    def __init__(self, review_service: ReviewService):
        self.review_service = review_service

    def trigger_review(
        self, project_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle POST /projects/{id}/review — trigger document review.

        Viewers cannot trigger reviews. Non-admins may only trigger reviews
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
            user_sub, _ = get_user_identity(event)
        except PermissionError as e:
            return error_response(403, str(e))
        except ValueError as e:
            return error_response(401, str(e))

        if role == UserRole.VIEWER:
            return error_response(403, "Viewers have read-only access")

        try:
            if role != UserRole.ADMIN:
                try:
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            logger.info(f"Trigger review: project={project_id} user_sub='{user_sub}'")
            result = self.review_service.trigger_review(project_id, user_sub=user_sub)

            if not result:
                return error_response(404, f"Project not found: {project_id}")

            return success_response(result, status_code=202)

        except ConflictError as e:
            return error_response(409, str(e))
        except ValueError as e:
            return error_response(400, str(e))
        except Exception as e:
            logger.error(f"Error triggering review: {e}", exc_info=True)
            return error_response(500, "Failed to trigger review")

    def get_review_plan(
        self, project_id: str, review_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle GET /projects/{id}/reviews/{reviewId}/plan — get review plan.

        Users may only access plans for their own projects. Admins and
        viewers can access any project's plan.

        Args:
            project_id: Project identifier.
            review_id: Review identifier.
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
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            result = self.review_service.get_review_plan(project_id, review_id)
            if not result:
                return error_response(404, "Review plan not found")
            return success_response(result)

        except Exception as e:
            logger.error(f"Error getting review plan: {e}", exc_info=True)
            return error_response(500, "Failed to get review plan")

    def approve_review_plan(
        self, project_id: str, review_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle POST /projects/{id}/reviews/{reviewId}/approve — approve plan.

        Viewers cannot approve plans. Non-admins may only approve plans for
        their own projects.

        Args:
            project_id: Project identifier.
            review_id: Review identifier.
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
            return error_response(403, "Viewers have read-only access")

        try:
            if role != UserRole.ADMIN:
                try:
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            req_ctx = event.get("requestContext", {})
            logger.info(
                f"Approve plan: project={project_id} review={review_id} "
                f"requestId={req_ctx.get('requestId', 'unknown')}"
            )

            import json

            body = json.loads(event.get("body", "{}") or "{}")
            plan_override = body.get("plan")

            result = self.review_service.approve_review_plan(
                project_id, review_id, plan_override=plan_override
            )
            return success_response(result)

        except ValueError as e:
            return error_response(400 if "not found" not in str(e).lower() else 404, str(e))
        except Exception as e:
            logger.error(f"Error approving review plan: {e}", exc_info=True)
            return error_response(500, "Failed to approve review plan")

    def reject_review_plan(
        self, project_id: str, review_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle POST /projects/{id}/reviews/{reviewId}/reject — reject plan.

        Viewers cannot reject plans. Non-admins may only reject plans for
        their own projects.

        Args:
            project_id: Project identifier.
            review_id: Review identifier.
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
            return error_response(403, "Viewers have read-only access")

        try:
            if role != UserRole.ADMIN:
                try:
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            import json

            body = json.loads(event.get("body", "{}") or "{}")
            reason = body.get("reason", "")

            result = self.review_service.reject_review_plan(project_id, review_id, reason=reason)
            return success_response(result)

        except ValueError as e:
            return error_response(400 if "not found" not in str(e).lower() else 404, str(e))
        except Exception as e:
            logger.error(f"Error rejecting review plan: {e}", exc_info=True)
            return error_response(500, "Failed to reject review plan")

    def abort_review(
        self, project_id: str, review_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle POST /projects/{id}/reviews/{reviewId}/abort — abort running review.

        Viewers cannot abort reviews. Non-admins may only abort reviews on
        their own projects.

        Args:
            project_id: Project identifier.
            review_id: Review identifier.
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
            return error_response(403, "Viewers have read-only access")

        try:
            if role != UserRole.ADMIN:
                try:
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            import json

            body = json.loads(event.get("body", "{}") or "{}")
            reason = body.get("reason", "")

            result = self.review_service.abort_review(project_id, review_id, reason=reason)
            return success_response(result)

        except ValueError as e:
            return error_response(400 if "not found" not in str(e).lower() else 404, str(e))
        except Exception as e:
            logger.error(f"Error aborting review: {e}", exc_info=True)
            return error_response(500, "Failed to abort review")

    def get_review_events(
        self, project_id: str, review_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle GET /projects/{id}/reviews/{reviewId}/events — get review event log.

        Users may only access events for their own projects. Admins and
        viewers can access any project's events.

        Query parameters:
            after: Optional ISO-8601 timestamp cursor. When provided, only
                events at or after this timestamp are returned.

        Args:
            project_id: Project identifier.
            review_id: Review identifier.
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
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            query_params = event.get("queryStringParameters") or {}
            after = query_params.get("after") or None

            result = self.review_service.get_review_events(
                project_id,
                review_id,
                after=after,
            )
            return success_response(result)

        except Exception as e:
            logger.error(f"Error getting review events: {e}", exc_info=True)
            return error_response(500, "Failed to get review events")

    def get_report(self, project_id: str, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /projects/{id}/report — generate markdown report.

        Users may only access reports for their own projects. Admins and
        viewers can access any project's report.

        Args:
            project_id: Project identifier.
            event: API Gateway event.
            context: Lambda context.

        Returns:
            API Gateway response with rendered markdown report.
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
                    self.review_service.verify_project_ownership(project_id, user_sub)
                except KeyError:
                    return error_response(404, f"Project not found: {project_id}")
                except PermissionError:
                    return error_response(403, "Access denied")

            markdown = self.review_service.generate_report(project_id)
            if markdown is None:
                return error_response(404, "No completed review found for this project")
            return success_response({"report": markdown, "content_type": "text/markdown"})

        except Exception as e:
            logger.error(f"Error generating report: {e}", exc_info=True)
            return error_response(500, "Failed to generate report")
