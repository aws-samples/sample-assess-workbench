"""
Post-Completion Error Handler — marks review as completed with warnings.

Invoked when a post-completion step (StoreResults, UpdateStatusCompleted)
fails after the review has already produced results. Instead of marking the
review as failed (which would discard valid findings), this handler sets
status to 'completed' and attaches warning details so the user knows
bookkeeping failed while results are still available.
"""

import logging
import os
from datetime import datetime, timezone

import boto3

from core.progress import send_progress, set_user_sub, set_review_context
from core.errors import extract_error_message

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
# Error handler — maximally defensive, all fields optional.
EXPECTED_EVENT = {
    "required": [],
    "optional": [
        "project_id",
        "review_id",
        "error",
        "connection_id",
        "user_sub",
        "websocket_endpoint",
    ],
}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ.get("DYNAMODB_TABLE_NAME", ""))


def lambda_handler(event: dict, context) -> dict:
    """Mark a project as completed with post-completion warnings.

    Args:
        event: Step Functions input containing:
            project_id: Project identifier.
            error: Error object from Step Functions Catch block.
            connection_id: WebSocket connection ID.
            websocket_endpoint: WebSocket management endpoint.
            user_sub: User identifier for WebSocket broadcast.
            review_id: Review identifier for event persistence.

    Returns:
        dict with status 'completed' and the warning message.

    Raises:
        Exception: If the DynamoDB status update fails, the exception
            propagates so the state machine's Catch routes to
            UpdateStatusFailed as a last resort.
    """
    project_id = event.get("project_id", "")
    raw_error = event.get("error", {})
    connection_id = event.get("connection_id", "")
    websocket_endpoint = event.get("websocket_endpoint", "")

    set_user_sub(event.get("user_sub", ""))
    set_review_context(project_id, event.get("review_id", ""))

    warning_message = extract_error_message(raw_error)

    logger.info(
        "Post-completion error for project %s — marking completed with warnings: %s",
        project_id,
        warning_message[:200],
    )

    # Store status as completed + attach warnings. If this fails, the
    # exception propagates and the state machine falls through to
    # UpdateStatusFailed — which is correct (we can't even mark it completed).
    _update_status_with_warnings(project_id, warning_message)

    # Notify the UI
    send_progress(
        connection_id,
        websocket_endpoint,
        "workflow_completed_with_warnings",
        {
            "warning": warning_message,
            "project_id": project_id,
        },
    )  # Don't fail the state machine over a notification

    return {
        "status": "completed",
        "project_id": project_id,
        "warning": warning_message,
    }


def _update_status_with_warnings(project_id: str, warning_message: str) -> None:
    """Set project status to completed and store post_completion_warnings.

    Args:
        project_id: Project identifier.
        warning_message: Truncated warning message to store.

    Raises:
        Exception: Propagates any DynamoDB write errors.
    """
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    table.update_item(
        Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"},
        UpdateExpression=(
            "SET #status = :status, updated_at = :ts, post_completion_warnings = :warnings"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "completed",
            ":ts": timestamp,
            ":warnings": warning_message,
        },
    )
