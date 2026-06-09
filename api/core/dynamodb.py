"""Shared DynamoDB operations and serialization helpers.

Centralises PK/SK schema knowledge for operations used across multiple
Lambdas. The REST API's DynamoDBDataAccess class handles its own queries;
this module covers the patterns duplicated in workflow Lambdas.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def convert_floats_to_decimal(obj: Any) -> Any:
    """Recursively convert float values to Decimal for DynamoDB.

    DynamoDB doesn't accept Python floats. This converts them to Decimal
    which the boto3 DynamoDB resource layer requires.

    Args:
        obj: Object to convert (can be dict, list, float, or other).

    Returns:
        Converted object with floats replaced by Decimal.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_floats_to_decimal(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# Project status
# ---------------------------------------------------------------------------


def update_project_status(
    table,
    project_id: str,
    status: str,
    error_message: Optional[str] = None,
    expected_status: Optional[str] = None,
) -> None:
    """Update a project's status in DynamoDB.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        status: New status value (e.g. 'failed', 'completed').
        error_message: Optional error message to store alongside the status.
        expected_status: If provided, the write only succeeds when the
            current status matches this value. Raises
            ConditionalCheckFailedException otherwise.

    Raises:
        Exception: Propagates any DynamoDB write errors (including
            ConditionalCheckFailedException when expected_status is supplied
            and the current status doesn't match).
    """
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    update_expr = 'SET #status = :status, updated_at = :ts'
    attr_names: Dict[str, str] = {'#status': 'status'}
    attr_values: Dict[str, Any] = {':status': status, ':ts': timestamp}

    if error_message is not None:
        update_expr += ', error_message = :err'
        attr_values[':err'] = error_message

    kwargs: Dict[str, Any] = {
        'Key': {'PK': f'PROJECT#{project_id}', 'SK': 'METADATA'},
        'UpdateExpression': update_expr,
        'ExpressionAttributeNames': attr_names,
        'ExpressionAttributeValues': attr_values,
    }

    if expected_status is not None:
        kwargs['ConditionExpression'] = '#status = :expected'
        attr_values[':expected'] = expected_status

    table.update_item(**kwargs)


# ---------------------------------------------------------------------------
# Review records
# ---------------------------------------------------------------------------

def store_review_record(
    table,
    project_id: str,
    review_id: str,
    *,
    status: str = 'completed',
    s3_bucket: str,
    findings_s3_key: str,
    created_at: str,
    duration_ms: int = 0,
) -> None:
    """Persist a review record to DynamoDB with an S3 reference to findings.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        review_id: Review identifier.
        status: Review status.
        s3_bucket: S3 bucket containing the findings JSON.
        findings_s3_key: S3 key for the findings JSON.
        created_at: ISO timestamp for the review.
        duration_ms: Review duration in milliseconds.

    Raises:
        Exception: Propagates any DynamoDB write errors.
    """
    table.put_item(Item={
        'PK': f'PROJECT#{project_id}',
        'SK': f'REVIEW#{created_at}',
        'review_id': review_id,
        'status': status,
        'findings_s3_bucket': s3_bucket,
        'findings_s3_key': findings_s3_key,
        'created_at': created_at,
        'duration_ms': duration_ms,
    })


# ---------------------------------------------------------------------------
# Plan storage
# ---------------------------------------------------------------------------

def store_plan(
    table,
    project_id: str,
    review_id: str,
    plan: Dict[str, Any],
    task_token: str,
    ttl: int,
) -> None:
    """Persist a review plan and task token to DynamoDB.

    The plan is stored as-is — callers should run convert_floats_to_decimal
    on it before passing it here.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        review_id: Review identifier.
        plan: The review plan dict (must already be DynamoDB-safe).
        task_token: Step Functions task token for the callback pattern.
        ttl: TTL epoch timestamp for automatic cleanup.

    Raises:
        Exception: Propagates any DynamoDB write errors.
    """
    now = datetime.now(tz=timezone.utc).isoformat()

    table.put_item(Item={
        'PK': f'PROJECT#{project_id}',
        'SK': f'PLAN#{review_id}',
        'plan': plan,
        'task_token': task_token,
        'status': 'pending_approval',
        'created_at': now,
        'ttl': ttl,
    })
