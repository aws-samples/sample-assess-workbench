"""
Update Status Failed Lambda — Robust error handler for the review workflow.

Replaces the direct DynamoDB updateItem in the UpdateStatusFailed state.
Guarantees the project status is set to 'failed' even when the error payload
is oversized or malformed. Truncates error messages and sends a WebSocket
event so the UI transitions to the failed state.
"""
import logging
import os
import boto3

from core.progress import send_progress, set_user_sub, set_review_context
from core.dynamodb import update_project_status
from core.errors import extract_error_message

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
# Error handler — maximally defensive, all fields optional.
EXPECTED_EVENT = {
    'required': [],
    'optional': ['project_id', 'error', 'connection_id', 'user_sub',
                 'websocket_endpoint', 'review_id'],
}

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ.get('DYNAMODB_TABLE_NAME', ''))


def lambda_handler(event: dict, context) -> dict:
    """Mark a project as failed with a truncated error message.

    Input:
        project_id: Project identifier
        error: Error object from Step Functions Catch (may be oversized)
        connection_id: WebSocket connection ID
        websocket_endpoint: WebSocket management endpoint
    """
    project_id = event.get('project_id', '')
    raw_error = event.get('error', {})
    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '')
    set_user_sub(event.get('user_sub', ''))
    set_review_context(event.get('project_id', ''), event.get('review_id', ''))

    # Guard: if DYNAMODB_TABLE_NAME wasn't configured, we can't mark anything
    # as failed. Log critically and return — the state machine's
    # UpdateStatusFailedFallback (bare DynamoDB write) is the backstop.
    if not table.table_name:
        logger.critical(
            "DYNAMODB_TABLE_NAME not configured — cannot mark projects as failed. "
            "All error handling will fall through to UpdateStatusFailedFallback."
        )
        return {'status': 'failed', 'project_id': project_id, 'error': 'misconfigured'}

    # Safely extract and truncate the error message
    error_message = extract_error_message(raw_error)

    logger.info(f"Marking project {project_id} as failed: {error_message[:200]}")

    try:
        update_project_status(table, project_id, 'failed', error_message=error_message)
    except Exception as e:
        # If the primary write fails, log critically and return. The stale
        # cleanup job (every 30 min) is the backstop — it will mark the
        # project as failed after the threshold. With PostCompletionErrorHandler
        # (WI1) handling post-completion failures, UpdateStatusFailed only
        # handles pre-completion errors, reducing the scope of what can land here.
        logger.critical(
            f"Status update failed for project {project_id}: {e}",
            exc_info=True,
        )

    # Notify the UI
    send_progress(connection_id, websocket_endpoint, 'workflow_failed', {
        'error': error_message,
        'project_id': project_id,
    })

    return {'status': 'failed', 'project_id': project_id}
