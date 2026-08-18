"""
Merge Quality Scores Lambda — Folds judge evaluation results into the findings payload.

Called after EvaluateQuality Map state completes. Takes the quality_results array
(one per agent) and merges each agent's scores into findings.reviews[agent].quality_scores.

Reads the full findings from S3 (stored by aggregate_results), merges quality scores,
and writes the updated findings back to S3. Returns only lightweight metadata to stay
under the Step Functions payload limit.
"""

import logging
import os

from core.progress import send_progress, set_user_sub, set_review_context
from core.s3 import read_json, write_json

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    "required": ["s3_bucket", "findings_s3_key"],
    "optional": [
        "quality_results",
        "quality_error",
        "project_id",
        "review_id",
        "connection_id",
        "user_sub",
        "websocket_endpoint",
    ],
}

WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT", "")


def lambda_handler(event: dict, context) -> dict:
    s3_bucket = event["s3_bucket"]
    findings_s3_key = event["findings_s3_key"]
    quality_results = event.get("quality_results", [])
    quality_error = event.get("quality_error")
    connection_id = event.get("connection_id", "")
    websocket_endpoint = event.get("websocket_endpoint", "") or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get("user_sub", ""))
    set_review_context(event.get("project_id", ""), event.get("review_id", ""))

    # Read findings from S3
    findings = read_json(s3_bucket, findings_s3_key)

    # Failure path: emit warning event and write findings unchanged
    if quality_error or not quality_results:
        error_msg = "Unknown error"
        if isinstance(quality_error, dict):
            error_msg = quality_error.get("Cause", quality_error.get("Error", str(quality_error)))
        elif quality_error:
            error_msg = str(quality_error)

        logger.warning(f"Judge evaluation failed: {error_msg}")

        send_progress(
            connection_id,
            websocket_endpoint,
            "quality_evaluation_failed",
            {
                "error": error_msg[:200],
            },
        )

        # Write findings back to S3 unchanged (quality_inputs already excluded)
        _write_findings_to_s3(s3_bucket, findings_s3_key, findings)

        _emit_review_complete(findings, connection_id, websocket_endpoint)

        return {"findings_s3_key": findings_s3_key}

    reviews = findings.get("reviews", {})

    # Merge each agent's quality scores into its review entry
    judge_metrics = {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0}
    judge_durations = {}
    scores_summary = {}

    for result in quality_results:
        agent_type = result.get("agent_type", "")
        evaluation = result.get("evaluation", {})
        metrics = result.get("metrics", {})

        if agent_type in reviews:
            scores = evaluation.get("scores_by_criterion", {})
            reviews[agent_type]["quality_scores"] = {
                "completeness": scores.get("completeness", 0),
                "specificity": scores.get("specificity", 0),
                "actionability": scores.get("actionability", 0),
                "overall": evaluation.get("overall_score", 0),
                "quality_met": evaluation.get("quality_met", True),
            }
            scores_summary[agent_type] = evaluation.get("overall_score", 0)

        judge_metrics["total_tokens"] += metrics.get("total_tokens", 0)
        judge_metrics["input_tokens"] += metrics.get("input_tokens", 0)
        judge_metrics["output_tokens"] += metrics.get("output_tokens", 0)

        # Track per-agent judge duration for the performance panel
        duration_s = metrics.get("duration_s")
        if duration_s is not None and agent_type:
            judge_durations[agent_type] = duration_s

    # Add judge metrics to the total metrics
    if findings.get("metrics"):
        findings["metrics"]["judge"] = judge_metrics
        if judge_durations:
            findings["metrics"]["judge"]["by_agent"] = judge_durations
        findings["metrics"]["total_tokens"] += judge_metrics["total_tokens"]

    # Write updated findings back to S3
    _write_findings_to_s3(s3_bucket, findings_s3_key, findings)

    # Emit completion event
    send_progress(
        connection_id,
        websocket_endpoint,
        "quality_evaluation_complete",
        {
            "scores": scores_summary,
        },
    )

    _emit_review_complete(findings, connection_id, websocket_endpoint)

    return {
        "findings_s3_key": findings_s3_key,
    }


def _write_findings_to_s3(s3_bucket: str, findings_s3_key: str, findings: dict) -> None:
    """Write updated findings back to S3."""
    write_json(s3_bucket, findings_s3_key, findings)


def _emit_review_complete(findings: dict, connection_id: str, websocket_endpoint: str) -> None:
    """Emit the final review_complete event with summary stats."""
    summary = findings.get("summary", {})
    metrics = findings.get("metrics", {})
    send_progress(
        connection_id,
        websocket_endpoint,
        "review_complete",
        {
            "total_findings": summary.get("total_findings", 0),
            "critical_severity": summary.get("critical_severity", 0),
            "high_severity": summary.get("high_severity", 0),
            "medium_severity": summary.get("medium_severity", 0),
            "low_severity": summary.get("low_severity", 0),
            "metrics": metrics,
        },
    )
