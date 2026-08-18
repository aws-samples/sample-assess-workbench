"""
Cleanup Stale Reviews Lambda — Scheduled via EventBridge every 30 minutes.

Scans for projects stuck at 'in_progress' for longer than the configured
threshold (default 2 hours). For each stale project, checks the Step Functions
execution state and marks the project as 'failed' if the execution is no
longer running.
"""

import logging
import os
import boto3
from datetime import datetime, timezone, timedelta

from core.dynamodb import update_project_status

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["DYNAMODB_TABLE_NAME"])
sfn_client = boto3.client("stepfunctions")

STALE_THRESHOLD_HOURS = int(os.environ.get("STALE_THRESHOLD_HOURS", "2"))


def lambda_handler(event: dict, context) -> dict:
    """Scan for and clean up stale in_progress projects."""
    threshold = datetime.now(tz=timezone.utc) - timedelta(hours=STALE_THRESHOLD_HOURS)
    threshold_iso = threshold.isoformat()

    logger.info(f"Scanning for projects in_progress before {threshold_iso}")

    # Query GSI for projects with status in_progress
    # Since we don't have a status GSI, scan with a filter
    stale_projects = _find_stale_projects(threshold_iso)

    if not stale_projects:
        logger.info("No stale projects found")
        return {"cleaned": 0}

    cleaned = 0
    for project in stale_projects:
        project_id = project["project_id"]
        execution_arn = project.get("execution_arn", "")

        try:
            if execution_arn:
                if _is_execution_running(execution_arn):
                    logger.info(f"Project {project_id} execution still running — skipping")
                    continue

            logger.info(f"Marking stale project {project_id} as failed")
            _mark_as_failed(project_id)
            cleaned += 1
        except Exception as e:
            # SFN unreachable or unexpected error — skip this project rather
            # than destructively marking a potentially running review as failed.
            logger.error(f"Skipping project {project_id} — could not verify execution state: {e}")

    logger.info(f"Cleaned {cleaned} stale projects")
    return {"cleaned": cleaned}


def _find_stale_projects(threshold_iso: str) -> list[dict]:
    """Find projects stuck at in_progress before the threshold.

    Uses GSI1 to query only project METADATA items (skips REVIEW#, CHAT#,
    FEEDBACK#, PLAN# items which don't have GSI1PK). Filters server-side
    for in_progress status and stale updated_at.
    """
    from boto3.dynamodb.conditions import Key, Attr

    stale = []
    query_kwargs = {
        "IndexName": "GSI1",
        "KeyConditionExpression": Key("GSI1PK").eq("PROJECT"),
        "FilterExpression": Attr("status").eq("in_progress") & Attr("updated_at").lt(threshold_iso),
        "ProjectionExpression": "project_id, execution_arn, updated_at",
    }

    while True:
        response = table.query(**query_kwargs)
        stale.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return stale


def _is_execution_running(execution_arn: str) -> bool:
    """Check if a Step Functions execution is still running.

    Args:
        execution_arn: Step Functions execution ARN.

    Returns:
        True if the execution is in RUNNING state, False if it completed
        or doesn't exist.

    Raises:
        Exception: If Step Functions is unreachable or returns an unexpected
            error. Callers should skip this project rather than assuming
            the execution is not running.
    """
    try:
        response = sfn_client.describe_execution(executionArn=execution_arn)
        return response["status"] == "RUNNING"
    except sfn_client.exceptions.ExecutionDoesNotExist:
        return False


def _mark_as_failed(project_id: str) -> None:
    """Mark a project as failed due to stale timeout.

    Uses a condition expression to only overwrite if the project is still
    in_progress — avoids clobbering a status that already transitioned
    (e.g. completed or already failed by the error handler).
    """
    try:
        update_project_status(
            table,
            project_id,
            "failed",
            error_message=f"Review timed out after {STALE_THRESHOLD_HOURS} hours — marked as failed by cleanup",
            expected_status="in_progress",
        )
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        logger.info(f"Project {project_id} status already changed — skipping")
    except Exception as e:
        logger.error(f"Failed to mark project {project_id} as failed: {e}")
