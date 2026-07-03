"""Strands agent plugins for tool-use governance.

Uses the Strands Plugin base class with @hook decorators for automatic
discovery of BeforeToolCallEvent and BeforeInvocationEvent handlers.
"""

import logging
from threading import Lock

from strands.hooks import BeforeInvocationEvent, BeforeToolCallEvent
from strands.plugins import Plugin, hook

logger = logging.getLogger(__name__)


class LimitToolCounts(Plugin):
    """Cap per-tool call counts to prevent runaway loops.

    Prevents one tool from burning the entire token budget without
    starving other tools. Each tool has an independent limit.
    Counts reset automatically at the start of each agent invocation.

    Args:
        max_tool_counts: Mapping of tool name to max allowed calls.
            Tools not in the map are unlimited.

    Example::

        LimitToolCounts(max_tool_counts={"search_findings": 4})
    """

    name = "limit-tool-counts"

    def __init__(self, max_tool_counts: dict[str, int]) -> None:
        super().__init__()
        self.max_tool_counts = max_tool_counts
        self.tool_counts: dict[str, int] = {}
        self._lock = Lock()

    @hook
    def reset_counts(self, event: BeforeInvocationEvent) -> None:
        """Reset counters at the start of each agent invocation."""
        with self._lock:
            self.tool_counts = {}

    @hook
    def intercept_tool(self, event: BeforeToolCallEvent) -> None:
        """Check and enforce per-tool call limits."""
        tool_name = event.tool_use["name"]

        with self._lock:
            max_count = self.max_tool_counts.get(tool_name)
            if max_count is None:
                return

            count = self.tool_counts.get(tool_name, 0) + 1
            self.tool_counts[tool_name] = count

        if count > max_count:
            logger.warning(
                "Tool %s hit call limit (%d/%d) — cancelling",
                tool_name,
                count,
                max_count,
            )
            event.cancel_tool = (
                f"Tool '{tool_name}' has reached its maximum of "
                f"{max_count} calls for this request. Use the results "
                f"you already have to answer the question."
            )
