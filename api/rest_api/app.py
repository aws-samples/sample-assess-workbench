"""
Lambda handler for AgentCore Risk Assessor API.
Provides project management, document review, and interactive chat with AI agents.
"""

import hmac
import logging
import os
import re
import boto3
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Callable

# Import layered components
from rest_api.data_access import (
    DynamoDBDataAccess,
    S3DataAccess,
    StepFunctionsDataAccess,
    GuardrailEventsAccess,
)
from rest_api.services import (
    ProjectService,
    ReviewService,
    ContextService,
    FeedbackService,
    AnalyticsService,
    AdminService,
    StandardsService,
)
from rest_api.handlers import (
    ProjectHandlers,
    ReviewHandlers,
    ContextHandlers,
    FeedbackHandlers,
    AnalyticsHandlers,
    AdminHandlers,
    StandardsHandlers,
)
from rest_api.utils import success_response, error_response
from rest_api.utils.auth import require_write_access

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Origin lockdown: in staging/prod, CloudFront injects X-Origin-Verify header.
# Requests without a valid header are rejected with 403. In dev (no CloudFront),
# the env var is empty and all requests pass through.
ORIGIN_VERIFY_SECRET = os.environ.get("ORIGIN_VERIFY_SECRET", "")

# Initialize data access layer (singleton pattern)
dynamodb_access = DynamoDBDataAccess()
s3_access = S3DataAccess()
stepfunctions_access = StepFunctionsDataAccess()

# Connections table for WebSocket connection lookup
_connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
_connections_table = (
    boto3.resource("dynamodb").Table(_connections_table_name) if _connections_table_name else None
)

# Initialize services
project_service = ProjectService(dynamodb_access, s3_access)
review_service = ReviewService(
    dynamodb_access, s3_access, stepfunctions_access, connections_table=_connections_table
)
context_service = ContextService(dynamodb_access, s3_access)
feedback_service = FeedbackService(dynamodb_access)
analytics_service = AnalyticsService(dynamodb_access)
guardrail_events_access = GuardrailEventsAccess()
admin_service = AdminService(dynamodb_access, guardrail_events=guardrail_events_access)

# Standards corpus — separate S3 bucket for compliance standards
_standards_bucket = os.environ.get("STANDARDS_BUCKET_NAME", "")
_standards_kb_id = os.environ.get("STANDARDS_KB_ID", "")
_standards_ds_id = os.environ.get("STANDARDS_DS_ID", "")
standards_s3 = S3DataAccess(bucket_name=_standards_bucket) if _standards_bucket else None
standards_service = (
    StandardsService(standards_s3, kb_id=_standards_kb_id, ds_id=_standards_ds_id)
    if standards_s3
    else None
)

# Initialize handlers
project_handlers = ProjectHandlers(project_service)
review_handlers = ReviewHandlers(review_service)
context_handlers = ContextHandlers(context_service)
feedback_handlers = FeedbackHandlers(feedback_service, project_service)
analytics_handlers = AnalyticsHandlers(analytics_service)
admin_handlers = AdminHandlers(admin_service)
standards_handlers = StandardsHandlers(standards_service) if standards_service else None


# ---------------------------------------------------------------------------
# Origin lockdown
# ---------------------------------------------------------------------------


def _verify_origin(event: Dict[str, Any]) -> bool:
    """Verify request came through CloudFront via the X-Origin-Verify header.

    In dev (no CloudFront), ORIGIN_VERIFY_SECRET is empty and all requests pass.
    In staging/prod, requests without a valid X-Origin-Verify header are rejected
    with 403 — hard lockdown, no bypass.

    Uses hmac.compare_digest for constant-time comparison to prevent timing attacks.

    Args:
        event: API Gateway v2 event dict containing headers.

    Returns:
        True if the request is allowed, False if it should be rejected.
    """
    if not ORIGIN_VERIFY_SECRET:
        return True  # Dev mode — no CloudFront in front

    headers = event.get("headers", {})
    header_value = headers.get("x-origin-verify", "")
    return hmac.compare_digest(header_value, ORIGIN_VERIFY_SECRET)


# ---------------------------------------------------------------------------
# Route table — (method, path_template, handler)
#
# Path templates use {param} placeholders, matched to named regex groups.
# More specific routes must come before less specific ones.
# Handlers are called as handler(*path_params, event, context) where
# path_params are the captured {param} values in URL order.
# ---------------------------------------------------------------------------


def _health(event, context):
    return success_response(
        {
            "status": "healthy",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
    )


def _standards_not_configured(event, context):
    return error_response(503, "Standards bucket not configured")


ROUTES: List[Tuple[str, str, Callable]] = [
    # Health / reference data
    ("GET", "/health", _health),
    ("GET", "/agents", admin_handlers.list_agents),
    # Projects
    ("POST", "/projects", require_write_access(project_handlers.create_project)),
    ("GET", "/projects", project_handlers.list_projects),
    ("GET", "/projects/{project_id}/document", project_handlers.get_project_document),
    ("POST", "/projects/{project_id}/review", review_handlers.trigger_review),
    ("GET", "/projects/{project_id}/reviews/{review_id}/plan", review_handlers.get_review_plan),
    (
        "POST",
        "/projects/{project_id}/reviews/{review_id}/approve",
        review_handlers.approve_review_plan,
    ),
    (
        "POST",
        "/projects/{project_id}/reviews/{review_id}/reject",
        review_handlers.reject_review_plan,
    ),
    ("POST", "/projects/{project_id}/reviews/{review_id}/abort", review_handlers.abort_review),
    ("GET", "/projects/{project_id}/reviews/{review_id}/events", review_handlers.get_review_events),
    ("GET", "/projects/{project_id}/report", review_handlers.get_report),
    ("POST", "/projects/{project_id}/feedback", feedback_handlers.submit_feedback),
    ("GET", "/projects/{project_id}/feedback", feedback_handlers.get_feedback),
    ("GET", "/projects/{project_id}", project_handlers.get_project),
    ("DELETE", "/projects/{project_id}", require_write_access(project_handlers.delete_project)),
    # Contexts
    ("POST", "/contexts", require_write_access(context_handlers.create_context)),
    ("GET", "/contexts", context_handlers.list_contexts),
    ("GET", "/contexts/{context_id}/content", context_handlers.get_context_content),
    (
        "PUT",
        "/contexts/{context_id}/content",
        require_write_access(context_handlers.update_context_content),
    ),
    ("GET", "/contexts/{context_id}", context_handlers.get_context),
    ("DELETE", "/contexts/{context_id}", require_write_access(context_handlers.delete_context)),
    # Analytics
    ("GET", "/analytics/summary", analytics_handlers.get_summary),
    ("GET", "/analytics/trends", analytics_handlers.get_trends),
    ("GET", "/analytics/coverage/{project_id}", analytics_handlers.get_coverage),
    # Admin — standards (specific paths before parameterized)
    (
        "GET",
        "/admin/standards/sync-status",
        standards_handlers.get_sync_status if standards_handlers else _standards_not_configured,
    ),
    (
        "POST",
        "/admin/standards/sync",
        require_write_access(standards_handlers.start_sync)
        if standards_handlers
        else _standards_not_configured,
    ),
    (
        "GET",
        "/admin/standards",
        standards_handlers.list_standards if standards_handlers else _standards_not_configured,
    ),
    (
        "POST",
        "/admin/standards",
        require_write_access(standards_handlers.upload_standard)
        if standards_handlers
        else _standards_not_configured,
    ),
    (
        "PUT",
        "/admin/standards/{standard_id}/metadata",
        require_write_access(standards_handlers.update_metadata)
        if standards_handlers
        else _standards_not_configured,
    ),
    (
        "DELETE",
        "/admin/standards/{standard_id}",
        require_write_access(standards_handlers.delete_standard)
        if standards_handlers
        else _standards_not_configured,
    ),
    ("GET", "/admin/registry", admin_handlers.list_registry),
    ("PUT", "/admin/registry/{agent_type}", require_write_access(admin_handlers.update_registry)),
    ("GET", "/admin/guardrail-events", admin_handlers.get_guardrail_events),
]


def _compile_route(pattern: str):
    """Convert a path template like '/projects/{project_id}' to a compiled regex."""
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    return re.compile(f"^{regex}$")


# Pre-compile all route patterns at module load (once per cold start)
_COMPILED_ROUTES = [
    (method, _compile_route(pattern), handler) for method, pattern, handler in ROUTES
]


def _resolve_route(http_method: str, path: str):
    """Match a request to a route. Returns (handler, path_params) or (None, None)."""
    for method, compiled, handler in _COMPILED_ROUTES:
        if method != http_method:
            continue
        match = compiled.match(path)
        if match:
            return handler, match.groupdict()
    return None, None


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler — resolves route and dispatches to handler."""
    try:
        # Origin lockdown: reject requests that didn't come through CloudFront
        if not _verify_origin(event):
            logger.warning("Origin verification failed — request did not come through CloudFront")
            return error_response(403, "Forbidden")

        # API Gateway v2 (HTTP API) format
        request_context = event.get("requestContext", {})
        http = request_context.get("http", {})
        stage = request_context.get("stage", "")

        http_method = http.get("method", event.get("httpMethod", "GET"))
        raw_path = http.get("path", event.get("path", "/"))

        # Strip stage prefix (e.g., /v1/health -> /health)
        if stage and raw_path.startswith(f"/{stage}/"):
            path = raw_path[len(stage) + 1 :]
        else:
            path = raw_path

        logger.info(f"Request: {http_method} {path} (raw: {raw_path})")

        handler, path_params = _resolve_route(http_method, path)
        if not handler:
            return error_response(404, "Not found", f"Path not found: {http_method} {path}")

        # Call handler with path params as positional args, then event and context
        args = list(path_params.values()) + [event, context]
        return handler(*args)

    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        return error_response(500, "Internal server error")
