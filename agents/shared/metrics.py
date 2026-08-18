"""Extract observability metrics from Strands AgentResult.

Metrics extraction is a non-critical side effect — findings are already
parsed by the time this runs. Failures here should log a warning and
return whatever partial metrics were collected, not propagate up and
break the review response.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_metrics(result: Any) -> dict[str, Any]:
    """Extract observability metrics from a Strands AgentResult.

    Collects token usage, cycle timing, model latency, and tool metrics
    from the result object. Returns partial metrics if extraction fails
    partway through.

    Args:
        result: A Strands AgentResult with a .metrics attribute.

    Returns:
        Dict of metric key-value pairs. Always returns a dict, even on
        failure (with whatever was collected before the error).
    """
    metrics: dict[str, Any] = {}
    try:
        m = result.metrics
        usage = m.accumulated_usage or {}
        metrics["input_tokens"] = usage.get("inputTokens", 0)
        metrics["output_tokens"] = usage.get("outputTokens", 0)
        metrics["total_tokens"] = usage.get("totalTokens", 0)
        metrics["cache_read_tokens"] = usage.get("cacheReadInputTokens", 0)
        metrics["cache_write_tokens"] = usage.get("cacheWriteInputTokens", 0)
        metrics["cycle_count"] = len(m.cycle_durations) if m.cycle_durations else 0
        metrics["total_duration_s"] = round(sum(m.cycle_durations), 2) if m.cycle_durations else 0
        latency = (m.accumulated_metrics or {}).get("latencyMs", 0)
        metrics["model_latency_ms"] = latency
        if m.tool_metrics:
            tools: dict[str, Any] = {}
            for name, tm in m.tool_metrics.items():
                tools[name] = {
                    "calls": tm.call_count,
                    "success_rate": round(tm.success_rate, 2)
                    if hasattr(tm, "success_rate")
                    else 1.0,
                    "total_time_s": round(tm.total_time, 2) if hasattr(tm, "total_time") else 0,
                }
            metrics["tools"] = tools
    except Exception:
        logger.warning("Failed to extract metrics from agent result", exc_info=True)
    return metrics
