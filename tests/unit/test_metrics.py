"""Tests for the shared metrics extraction module."""

import logging
from unittest.mock import MagicMock

from shared.metrics import extract_metrics


def _make_result(
    usage=None,
    cycle_durations=None,
    accumulated_metrics=None,
    tool_metrics=None,
):
    """Build a mock AgentResult with the given metrics."""
    result = MagicMock()
    result.metrics.accumulated_usage = usage or {}
    result.metrics.cycle_durations = cycle_durations
    result.metrics.accumulated_metrics = accumulated_metrics
    result.metrics.tool_metrics = tool_metrics
    return result


class TestExtractMetrics:

    def test_extracts_token_usage(self):
        result = _make_result(usage={
            "inputTokens": 100,
            "outputTokens": 50,
            "totalTokens": 150,
            "cacheReadInputTokens": 10,
            "cacheWriteInputTokens": 5,
        })
        metrics = extract_metrics(result)
        assert metrics["input_tokens"] == 100
        assert metrics["output_tokens"] == 50
        assert metrics["total_tokens"] == 150
        assert metrics["cache_read_tokens"] == 10
        assert metrics["cache_write_tokens"] == 5

    def test_defaults_missing_usage_to_zero(self):
        result = _make_result(usage={})
        metrics = extract_metrics(result)
        assert metrics["input_tokens"] == 0
        assert metrics["output_tokens"] == 0

    def test_extracts_cycle_durations(self):
        result = _make_result(cycle_durations=[1.5, 2.3, 0.7])
        metrics = extract_metrics(result)
        assert metrics["cycle_count"] == 3
        assert metrics["total_duration_s"] == 4.5

    def test_no_cycle_durations(self):
        result = _make_result(cycle_durations=None)
        metrics = extract_metrics(result)
        assert metrics["cycle_count"] == 0
        assert metrics["total_duration_s"] == 0

    def test_extracts_model_latency(self):
        result = _make_result(accumulated_metrics={"latencyMs": 1234})
        metrics = extract_metrics(result)
        assert metrics["model_latency_ms"] == 1234

    def test_no_accumulated_metrics(self):
        result = _make_result(accumulated_metrics=None)
        metrics = extract_metrics(result)
        assert metrics["model_latency_ms"] == 0

    def test_extracts_tool_metrics(self):
        tm = MagicMock()
        tm.call_count = 3
        tm.success_rate = 0.667
        tm.total_time = 1.234
        result = _make_result(tool_metrics={"my_tool": tm})
        metrics = extract_metrics(result)
        assert metrics["tools"]["my_tool"]["calls"] == 3
        assert metrics["tools"]["my_tool"]["success_rate"] == 0.67
        assert metrics["tools"]["my_tool"]["total_time_s"] == 1.23

    def test_tool_without_success_rate_defaults(self):
        tm = MagicMock(spec=["call_count", "total_time"])
        tm.call_count = 1
        tm.total_time = 0.5
        result = _make_result(tool_metrics={"tool": tm})
        metrics = extract_metrics(result)
        assert metrics["tools"]["tool"]["success_rate"] == 1.0

    def test_no_tool_metrics(self):
        result = _make_result(tool_metrics=None)
        metrics = extract_metrics(result)
        assert "tools" not in metrics

    def test_no_error_key_on_success(self):
        result = _make_result()
        metrics = extract_metrics(result)
        assert "_error" not in metrics

    def test_returns_partial_metrics_on_failure(self, caplog):
        """If extraction fails partway, return what was collected and log."""
        result = MagicMock()
        result.metrics.accumulated_usage = {"inputTokens": 42}
        # Make cycle_durations blow up
        result.metrics.cycle_durations = "not-a-list"
        result.metrics.accumulated_metrics = None
        result.metrics.tool_metrics = None

        with caplog.at_level(logging.WARNING):
            metrics = extract_metrics(result)

        # Should have collected input_tokens before the failure
        assert metrics.get("input_tokens") == 42
        # Should NOT have the old _error key
        assert "_error" not in metrics
        # Should have logged a warning
        assert "Failed to extract metrics" in caplog.text

    def test_no_error_key_on_failure(self):
        """The old _error key pattern is gone — failures log, not stuff keys."""
        result = MagicMock()
        result.metrics = None  # Will cause AttributeError

        metrics = extract_metrics(result)
        assert "_error" not in metrics
