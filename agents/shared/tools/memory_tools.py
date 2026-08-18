"""Agent tools for searching AgentCore Memory.

Shared across all chat (and later review) agents. Each tool is a thin
wrapper around ``_search_memory`` — validate inputs, construct the
namespace, format the response for the LLM.

Per-request context (project_id, memory_id, agent_type) is passed via
Strands ``invocation_state`` so it doesn't appear in the LLM prompt.

Error handling: the ``handle_tool_errors`` decorator from ``errors.py``
sits on each tool function (not on ``_search_memory``), catching expected
AWS API errors at the tool-to-LLM boundary and returning ``[ERROR]``
prefixed strings. Programming errors propagate to Strands' error handling.
"""

import logging
from typing import Any

import boto3
from strands import tool
from strands.types.tools import ToolContext

from shared.tools.errors import handle_tool_errors

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10


def _get_agentcore_client():
    """Create a bedrock-agentcore client per call.

    AgentCore containers handle concurrent requests (unlike Lambda which
    serializes). boto3 clients are not thread-safe, and we can't guarantee
    the framework's concurrency model (asyncio vs thread pool). Per-call
    creation is safe regardless, and the ~1ms overhead is negligible vs
    the ~200ms API call.
    """
    return boto3.client("bedrock-agentcore")


def _search_memory(
    memory_id: str,
    namespace: str,
    query: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Semantic search over an AgentCore Memory namespace.

    Args:
        memory_id: The AgentCore Memory resource ID to query.
        namespace: The namespace to search within
            (e.g. ``/findings/{project_id}/security``).
        query: Semantic search query.
        top_k: Maximum number of results to return.

    Returns:
        List of memory record dicts with ``content`` and ``score`` keys.

    Raises:
        ClientError: On AWS API failure.
        BotoCoreError: On SDK-level failure.
        EndpointConnectionError: On connectivity failure.
    """
    client = _get_agentcore_client()
    response = client.retrieve_memory_records(
        memoryId=memory_id,
        namespace=namespace,
        searchCriteria={"searchQuery": query, "topK": top_k},
    )
    return response.get("memoryRecordSummaries", [])


@tool(context=True)
@handle_tool_errors
def search_findings(query: str, tool_context: ToolContext = None) -> str:
    """Search review findings from your domain.

    Use this to look up specific findings, recommendations, or issues
    from the review. Craft targeted queries for best results.

    Args:
        query: Semantic search query describing what you're looking for.
    """
    project_id = tool_context.invocation_state.get("project_id")
    memory_id = tool_context.invocation_state.get("memory_id")
    agent_type = tool_context.invocation_state.get("self_agent_type")

    # Fail visibly rather than constructing a bad namespace like
    # "/findings/None/None" — these are programming errors in the
    # wiring, not expected runtime conditions.
    if not all([project_id, memory_id, agent_type]):
        missing = [
            k
            for k, v in {
                "project_id": project_id,
                "memory_id": memory_id,
                "self_agent_type": agent_type,
            }.items()
            if not v
        ]
        raise ValueError(f"search_findings missing required invocation_state: {missing}")

    namespace = f"/findings/{project_id}/{agent_type}"
    records = _search_memory(memory_id, namespace, query)
    if not records:
        return "No findings matched your query."
    return "\n\n".join(r.get("content", {}).get("text", "") for r in records)


@tool(context=True)
@handle_tool_errors
def get_prior_findings(
    agent_type: str,
    query: str = "",
    tool_context: ToolContext = None,
) -> str:
    """Retrieve findings from another agent's review of this document.

    Use when your analysis would benefit from another perspective.
    For example, the risk agent might want to see security findings
    about authentication before assessing operational risk.

    Args:
        agent_type: The agent whose findings to retrieve — an agent_type
            value from the agent registry (e.g. "security", "risk",
            "architecture"). Must be a different agent than yourself.
        query: Optional semantic filter. If empty, returns all findings
            from that agent. If provided, returns only relevant matches.
    """
    project_id = tool_context.invocation_state.get("project_id")
    memory_id = tool_context.invocation_state.get("memory_id")
    self_agent_type = tool_context.invocation_state.get("self_agent_type")

    if not all([project_id, memory_id]):
        missing = [
            k
            for k, v in {
                "project_id": project_id,
                "memory_id": memory_id,
            }.items()
            if not v
        ]
        raise ValueError(f"get_prior_findings missing required invocation_state: {missing}")

    if agent_type == self_agent_type:
        return (
            f"You are the {self_agent_type} agent — use your own analysis "
            f"instead of searching your own findings. To search other agents' "
            f"findings, specify a different agent_type."
        )

    namespace = f"/findings/{project_id}/{agent_type}"
    search_query = query or f"all {agent_type} findings"
    records = _search_memory(memory_id, namespace, search_query)
    if not records:
        return (
            f"No findings from the {agent_type} agent are available. "
            f"That agent may not have run yet or produced no findings."
        )
    return "\n\n".join(r.get("content", {}).get("text", "") for r in records)
