"""
Aggregate Results Lambda — Combines all agent findings, computes stats, stores in memory.
Final processing step before DynamoDB storage.

Stores the full findings payload in S3 to avoid exceeding the 256KB Step Functions
payload limit. Only lightweight references (s3_bucket + findings_s3_key) flow through
the state machine. Downstream Lambdas (invoke_judge, merge_quality, store_results)
read from S3 on demand.
"""

import logging
import os
import boto3
from datetime import datetime, timezone

from core.progress import send_progress, set_user_sub, set_review_context
from core.s3 import write_json
from core.review_processing import flatten_results, compute_summary, build_quality_inputs
from core.memory import build_finding_records, store_records_in_memory

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    "required": ["project_id", "review_id", "s3_bucket", "execution_start_time"],
    "optional": [
        "project_name",
        "project_description",
        "plan",
        "group_results",
        "connection_id",
        "user_sub",
        "websocket_endpoint",
        "image_analysis_metrics",
        "document_s3_key",
        "planning_duration_ms",
    ],
}

agentcore_client = boto3.client("bedrock-agentcore")

SHARED_MEMORY_ARN = os.environ.get("SHARED_MEMORY_ARN", "")
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT", "")


def lambda_handler(event: dict, context) -> dict:
    project_id = event["project_id"]
    review_id = event["review_id"]
    project_name = event.get("project_name", "Unknown")
    project_description = event.get("project_description", "")
    plan = event.get("plan", {})
    connection_id = event.get("connection_id", "")
    websocket_endpoint = event.get("websocket_endpoint", "") or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get("user_sub", ""))
    set_review_context(event.get("project_id", ""), event.get("review_id", ""))

    reviews, agent_statuses, total_metrics = flatten_results(
        event.get("group_results", []),
    )

    # Notify progress for non-completed agents
    for agent_type, status_info in agent_statuses.items():
        if status_info["status"] != "completed":
            send_progress(
                connection_id,
                websocket_endpoint,
                f"agent_{status_info['status']}",
                {
                    "agent": agent_type,
                    "status": status_info["status"],
                    "status_reason": status_info["status_reason"],
                    "finding_count": len(reviews.get(agent_type, {}).get("findings", [])),
                },
            )

    summary = compute_summary(reviews)

    # Store findings in AgentCore Memory
    record_count = 0
    if SHARED_MEMORY_ARN and reviews:
        try:
            record_count = _store_findings_in_memory(
                reviews, project_id, project_name, project_description
            )
            send_progress(
                connection_id,
                websocket_endpoint,
                "memory_write",
                {
                    "records": record_count,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to store findings in memory: {e}")

    # Include image analysis metrics if present
    image_analysis_metrics = event.get("image_analysis_metrics", {})
    if image_analysis_metrics and image_analysis_metrics.get("total_tokens", 0) > 0:
        total_metrics["image_analysis"] = image_analysis_metrics
        total_metrics["total_tokens"] += image_analysis_metrics.get("total_tokens", 0)

    send_progress(
        connection_id,
        websocket_endpoint,
        "aggregation_complete",
        {
            "total_findings": summary["total_findings"],
            "critical_severity": summary["critical_severity"],
            "high_severity": summary["high_severity"],
            "medium_severity": summary["medium_severity"],
            "low_severity": summary["low_severity"],
            "metrics": total_metrics,
        },
    )

    quality_inputs = build_quality_inputs(reviews, plan)

    if quality_inputs:
        send_progress(
            connection_id,
            websocket_endpoint,
            "quality_evaluation_started",
            {
                "agent_count": len(quality_inputs),
            },
        )

    created_at = datetime.now(tz=timezone.utc).isoformat()

    # Store findings in S3 (256KB Step Functions payload limit)
    findings_payload = {
        "reviews": reviews,
        "summary": summary,
        "plan": plan,
        "metrics": total_metrics,
    }

    # Include planning duration if available (flows from plan_review.py
    # through the ASL into this Lambda's event payload).
    planning_duration_ms = event.get("planning_duration_ms")
    if planning_duration_ms is not None:
        findings_payload["metrics"]["planning_duration_ms"] = planning_duration_ms

    s3_bucket = event["s3_bucket"]
    findings_s3_key = f"projects/{project_id}/reviews/{review_id}/findings.json"
    write_json(s3_bucket, findings_s3_key, findings_payload)
    logger.info(f"Stored findings in S3: s3://{s3_bucket}/{findings_s3_key}")

    # Compute wall-clock duration from the Step Functions execution start time.
    start = datetime.fromisoformat(
        event["execution_start_time"].replace("Z", "+00:00"),
    )
    duration_ms = int((datetime.now(tz=timezone.utc) - start).total_seconds() * 1000)

    # Return only fields that the state machine's Assign block extracts.
    # Context fields (project_id, s3_bucket, etc.) are already in workflow
    # variables — no need to echo them back. Summary is stored in the S3
    # findings payload and not extracted by the state machine.
    # Participating agent types — used by chat agents to accurately
    # direct users to other agents' findings (Phase 2e).
    # Stored as comma-separated string for simple DynamoDB String
    # attribute via the Step Functions DynamoDB integration.
    participating_agents = ",".join(sorted(reviews.keys()))

    return {
        "status": "completed",
        "findings_s3_key": findings_s3_key,
        "quality_inputs": quality_inputs,
        "created_at": created_at,
        "duration_ms": duration_ms,
        "participating_agents": participating_agents,
    }


def _store_findings_in_memory(
    reviews: dict,
    project_id: str,
    project_name: str,
    project_description: str,
) -> int:
    """Store review findings in AgentCore Memory for semantic search.

    Uses the shared record-building logic from ``core.memory`` to ensure
    consistent format with the per-agent writes in ``invoke_review_agent.py``.
    AgentCore deduplicates on ``requestIdentifier``, so records already
    written per-agent are no-ops here.
    """
    memory_id = SHARED_MEMORY_ARN.split("/")[-1]
    records = []

    for agent_type, review_data in reviews.items():
        records.extend(
            build_finding_records(
                findings=review_data.get("findings", []),
                agent_type=agent_type,
                project_id=project_id,
                project_name=project_name,
            )
        )

    if not records:
        return 0

    return store_records_in_memory(agentcore_client, memory_id, records)
