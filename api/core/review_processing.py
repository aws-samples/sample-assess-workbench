"""Pure logic for processing agent review results.

Extracted from workflow/aggregate_results.py for testability and reuse.
These functions have no AWS dependencies — they transform data in memory.
"""

import logging

logger = logging.getLogger(__name__)


def flatten_results(
    group_results: list[list[dict]],
) -> tuple[dict, dict, dict]:
    """Flatten nested group results into a reviews dict and accumulated metrics.

    Args:
        group_results: List of groups, each group is a list of agent result dicts.
            Each agent result has: agent_type, findings, summary, status,
            status_reason, metrics.

    Returns:
        Tuple of (reviews, agent_statuses, total_metrics):
        - reviews: {agent_type: {findings, summary, status, status_reason}}
        - agent_statuses: {agent_type: {status, status_reason}}
        - total_metrics: accumulated token counts and per-agent breakdowns
    """
    reviews = {}
    agent_statuses = {}
    total_metrics = {
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_cycles": 0,
        "by_agent": {},
    }
    for group in group_results:
        for agent_result in group:
            agent_type = agent_result.get("agent_type")
            if not agent_type:
                logger.warning(
                    f"Skipping malformed agent result (no agent_type): {str(agent_result)[:200]}"
                )
                continue

            agent_status = agent_result.get("status", "completed")
            agent_statuses[agent_type] = {
                "status": agent_status,
                "status_reason": agent_result.get("status_reason", ""),
            }

            reviews[agent_type] = {
                "findings": agent_result.get("findings", []),
                "summary": agent_result.get("summary", ""),
                "status": agent_status,
                "status_reason": agent_result.get("status_reason", ""),
            }

            am = agent_result.get("metrics", {})
            if am:
                total_metrics["total_tokens"] += am.get("total_tokens", 0)
                total_metrics["input_tokens"] += am.get("input_tokens", 0)
                total_metrics["output_tokens"] += am.get("output_tokens", 0)
                total_metrics["cache_read_tokens"] += am.get("cache_read_tokens", 0)
                total_metrics["cache_write_tokens"] += am.get("cache_write_tokens", 0)
                total_metrics["total_cycles"] += am.get("cycle_count", 0)
                total_metrics["by_agent"][agent_type] = {
                    "total_tokens": am.get("total_tokens", 0),
                    "input_tokens": am.get("input_tokens", 0),
                    "output_tokens": am.get("output_tokens", 0),
                    "cycle_count": am.get("cycle_count", 0),
                    "total_duration_s": am.get("total_duration_s", 0),
                    "model_latency_ms": am.get("model_latency_ms", 0),
                    "lambda_duration_s": am.get("lambda_duration_s", 0),
                }

            # Coach durations list (populated when judge coaching is enabled)
            coach_durations = agent_result.get("coach_durations", [])
            if coach_durations:
                total_metrics["by_agent"].setdefault(agent_type, {})
                total_metrics["by_agent"][agent_type]["coach_durations"] = coach_durations

    return reviews, agent_statuses, total_metrics


def compute_summary(reviews: dict) -> dict:
    """Compute severity counts and per-agent finding counts.

    Args:
        reviews: Dict of {agent_type: {findings: [...], ...}} as returned
                 by flatten_results().

    Returns:
        Dict with total_findings, critical/high/medium/low severity counts,
        and by_agent finding counts.
    """
    total_findings = 0
    critical_severity = 0
    high_severity = 0
    medium_severity = 0
    low_severity = 0
    by_agent = {}

    for agent_type, review_data in reviews.items():
        findings = review_data.get("findings", [])
        count = len(findings)
        by_agent[agent_type] = count
        total_findings += count

        for finding in findings:
            severity = finding.get("severity", "").lower()
            if severity == "critical":
                critical_severity += 1
            elif severity == "high":
                high_severity += 1
            elif severity == "medium":
                medium_severity += 1
            elif severity == "low":
                low_severity += 1

    return {
        "total_findings": total_findings,
        "critical_severity": critical_severity,
        "high_severity": high_severity,
        "medium_severity": medium_severity,
        "low_severity": low_severity,
        "by_agent": by_agent,
    }


def build_quality_inputs(reviews: dict, plan: dict) -> list[dict]:
    """Build lightweight quality evaluation inputs for the judge Map state.

    Args:
        reviews: Dict of {agent_type: {findings: [...], ...}}.
        plan: The review plan dict containing groups with agent configs.

    Returns:
        List of dicts, one per agent, with agent_type, focus_areas,
        and coach_guidance extracted from the plan.
    """
    quality_inputs = []
    for agent_type in reviews:
        agent_focus_areas = []
        agent_coach_guidance = ""
        for group in plan.get("groups", []):
            for agent_cfg in group.get("agents", []):
                if agent_cfg.get("agent_type") == agent_type:
                    agent_focus_areas = agent_cfg.get("focus_areas", [])
                    agent_coach_guidance = agent_cfg.get("coach_guidance", "")
                    break
        quality_inputs.append(
            {
                "agent_type": agent_type,
                "focus_areas": agent_focus_areas,
                "coach_guidance": agent_coach_guidance,
            }
        )
    return quality_inputs
