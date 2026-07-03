"""
Invoke Judge Lambda — Evaluates quality of agent findings using Bedrock Converse.

Scores findings against the document and focus areas on three criteria:
completeness, specificity, and actionability. Uses tool use to guarantee
structured JSON output (same pattern as plan_review.py).

Modes:
  - evaluate: Post-processing quality scoring (Phase 1)
  - coach: Runtime refinement loop — scores findings and provides critique
    for the agent to improve on the next iteration (Phase 2)
"""

import logging
import os
import time
import boto3

from core.progress import send_progress, set_user_sub, set_review_context
from core.coach_logic import build_judge_prompt, normalize_evaluation, check_early_exit, JUDGE_TOOL
from core.s3 import read_json

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
# This Lambda is called in two modes (coach and evaluate) with overlapping fields.
EXPECTED_EVENT = {
    "required": ["agent_type"],
    "optional": [
        "focus_areas",
        "quality_threshold",
        "mode",
        "iteration",
        "prior_critique",
        "prior_score",
        "consecutive_drops",
        "coach_durations",
        "coach_guidance",
        "findings",
        "summary",
        "s3_bucket",
        "document_s3_key",
        "findings_s3_key",
        "document_preview",
        "project_id",
        "review_id",
        "connection_id",
        "user_sub",
        "websocket_endpoint",
    ],
}

bedrock = boto3.client("bedrock-runtime")

WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT", "")
JUDGE_MODEL_ID = os.environ.get("JUDGE_MODEL_ID")
if not JUDGE_MODEL_ID:
    raise RuntimeError(
        "JUDGE_MODEL_ID environment variable is required but not set. "
        "Check the Lambda configuration."
    )


def _load_context_from_s3(
    event: dict,
    agent_type: str,
    findings: list,
    summary: str,
) -> tuple[list, str, str]:
    """Load findings and document preview from S3 when not passed directly.

    Args:
        event: Lambda event dict with S3 references.
        agent_type: Agent type to extract findings for.
        findings: Pre-loaded findings list (may be empty).
        summary: Pre-loaded summary string.

    Returns:
        Tuple of (findings, summary, document_preview).

    Raises:
        RuntimeError: If S3 references exist but reads fail.
    """
    s3_bucket = event.get("s3_bucket", "")

    # Load findings from S3 (evaluate mode — aggregate_results stores them)
    if not findings:
        findings_s3_key = event.get("findings_s3_key", "")
        if s3_bucket and findings_s3_key:
            findings_data = read_json(s3_bucket, findings_s3_key)
            agent_review = findings_data.get("reviews", {}).get(agent_type, {})
            findings = agent_review.get("findings", [])
            summary = summary or agent_review.get("summary", "")

    # Load document preview from S3 (coach mode, to avoid payload bloat)
    document_preview = event.get("document_preview", "")
    if not document_preview:
        document_s3_key = event.get("document_s3_key", "")
        if s3_bucket and document_s3_key:
            doc_data = read_json(s3_bucket, document_s3_key)
            document_preview = doc_data.get("document_content", "")[:10000]

    return findings, summary, document_preview


def lambda_handler(event: dict, context) -> dict:
    agent_type = event["agent_type"]
    focus_areas = event.get("focus_areas", [])
    quality_threshold = float(event.get("quality_threshold", 0.8))
    mode = event.get("mode", "evaluate")
    iteration = event.get("iteration", 0)
    prior_critique = event.get("prior_critique", "")
    connection_id = event.get("connection_id", "")
    websocket_endpoint = event.get("websocket_endpoint", "") or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get("user_sub", ""))
    set_review_context(event.get("project_id", ""), event.get("review_id", ""))

    # Resolve findings and document preview (may require S3 reads)
    findings, summary, document_preview = _load_context_from_s3(
        event,
        agent_type,
        event.get("findings", []),
        event.get("summary", ""),
    )

    # Build the prompt
    prompt_text = build_judge_prompt(
        agent_type=agent_type,
        quality_threshold=quality_threshold,
        coach_guidance=event.get("coach_guidance", ""),
        document_preview=document_preview,
        focus_areas=focus_areas,
        findings=findings,
        mode=mode,
        iteration=iteration,
        prior_critique=prior_critique,
    )

    send_progress(
        connection_id,
        websocket_endpoint,
        "judge_started",
        {
            "agent": agent_type,
            "mode": mode,
            "iteration": iteration,
        },
    )

    # Call Bedrock Converse with tool use
    judge_start = time.time()
    response = bedrock.converse(
        modelId=JUDGE_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt_text}]}],
        inferenceConfig={"maxTokens": 2048, "temperature": 0.1},
        toolConfig={
            "tools": [JUDGE_TOOL],
            "toolChoice": {"tool": {"name": "submit_evaluation"}},
        },
    )

    # Extract structured result
    evaluation = None
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            evaluation = block["toolUse"]["input"]
            break

    if not evaluation:
        raise RuntimeError(
            f"Judge did not return tool use for {agent_type} — unexpected Bedrock response format"
        )

    evaluation, overall, raw_avg = normalize_evaluation(evaluation, quality_threshold)
    early_exit, consecutive_drops = check_early_exit(
        evaluation,
        overall,
        mode,
        iteration,
        float(event.get("prior_score", 0)),
        int(event.get("consecutive_drops", 0)),
    )

    scores = evaluation["scores_by_criterion"]
    logger.info(
        f"Judge {mode} for {agent_type}: scores=({scores['completeness']:.2f}, {scores['specificity']:.2f}, {scores['actionability']:.2f}) "
        f"raw_avg={raw_avg:.4f} overall={overall:.2f} threshold={quality_threshold:.2f} "
        f"quality_met={evaluation['quality_met']}{f' early_exit={early_exit}' if early_exit else ''}"
    )

    # Extract token metrics
    usage = response.get("usage", {})
    duration_s = round(time.time() - judge_start, 2)
    metrics = {
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "total_tokens": usage.get("inputTokens", 0) + usage.get("outputTokens", 0),
        "duration_s": duration_s,
    }

    # Emit WebSocket event
    if mode == "coach":
        send_progress(
            connection_id,
            websocket_endpoint,
            "judge_evaluated",
            {
                "agent": agent_type,
                "score": overall,
                "quality_met": evaluation["quality_met"],
                "iteration": iteration,
                "critique_summary": (evaluation.get("critique", "") or "")[:200],
                "early_exit": early_exit or None,
            },
        )
    else:
        send_progress(
            connection_id,
            websocket_endpoint,
            "quality_score",
            {
                "agent": agent_type,
                "overall": overall,
                "scores": scores,
                "quality_met": evaluation["quality_met"],
            },
        )

    # Accumulate coach durations list (coach mode only).
    # The ASL passes the prior list in; we append this iteration's duration.
    coach_durations: list[float] = list(event.get("coach_durations", []))
    if mode == "coach":
        coach_durations.append(duration_s)

    return {
        "agent_type": agent_type,
        "mode": mode,
        "iteration": iteration,
        "evaluation": evaluation,
        "metrics": metrics,
        "overall_score": overall,
        "consecutive_drops": consecutive_drops,
        "coach_durations": coach_durations,
    }
