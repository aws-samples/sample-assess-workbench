"""
Store Results Lambda — Persists a review record to DynamoDB.

Stores an S3 reference to the findings JSON (written by aggregate_results,
updated by merge_quality) rather than the findings blob itself. This avoids
the 400KB DynamoDB item size limit that large multi-agent reviews can exceed.
"""

import logging
import os
import boto3

from core.dynamodb import store_review_record

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    "required": ["project_id", "review_id", "s3_bucket", "findings_s3_key", "created_at"],
    "optional": ["status", "duration_ms", "connection_id", "user_sub", "websocket_endpoint"],
}

dynamodb = boto3.resource("dynamodb")

DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]


def lambda_handler(event: dict, context) -> dict:
    project_id = event["project_id"]
    review_id = event["review_id"]
    status = event.get("status", "completed")
    s3_bucket = event["s3_bucket"]
    findings_s3_key = event["findings_s3_key"]
    created_at = event["created_at"]
    duration_ms = event.get("duration_ms", 0)

    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    store_review_record(
        table,
        project_id,
        review_id,
        status=status,
        s3_bucket=s3_bucket,
        findings_s3_key=findings_s3_key,
        created_at=created_at,
        duration_ms=duration_ms,
    )

    # Project status is managed by the state machine (UpdateStatusCompleted /
    # UpdateStatusFailed states), not by this Lambda.  A previous
    # update_project_status() call here caused the "completed review shows as
    # failed" bug: the store_results IAM role only grants dynamodb:PutItem,
    # so the UpdateItem call threw AccessDeniedException, the state machine
    # caught it and routed to UpdateStatusFailed, overwriting the correct
    # status even though the review had completed successfully.

    logger.info(f"Stored review {review_id} for project {project_id}, status={status}")

    # The state machine discards this return value (ResultPath: null), but
    # a minimal return aids CloudWatch log readability.
    return {"status": status}
