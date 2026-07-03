"""AgentCore response parsing.

Canonical parser for AgentCore invoke_agent_runtime responses. Handles
multiple response shapes (SSE streaming, payload, body).
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def parse_agentcore_response(response: Dict[str, Any]) -> str:
    """Parse an AgentCore invoke response into text.

    Tries multiple response shapes (streaming iter_lines, payload, body)
    and validates that the result is non-empty.

    Args:
        response: The dict returned by agentcore_client.invoke_agent_runtime().

    Returns:
        The response text content.

    Raises:
        ValueError: If the response is empty after parsing.
    """
    result_text = ""

    if "response" in response:
        for line in response["response"].iter_lines():
            if line:
                result_text += line.decode("utf-8")
    else:
        body = response.get("payload", response.get("body", b""))
        if hasattr(body, "read"):
            result_text = body.read().decode("utf-8")
        elif isinstance(body, bytes):
            result_text = body.decode("utf-8")
        else:
            result_text = str(body)

    if not result_text.strip():
        raise ValueError("AgentCore returned an empty response")

    return result_text
