"""Shared error handling for agent tools.

All tool modules (``memory_tools``, ``kb_tools``) use the
``handle_tool_errors`` decorator to catch expected AWS API errors at
the tool-to-LLM boundary. Extracted here so tool modules don't
cross-import from each other.
"""

import functools
import logging

from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

logger = logging.getLogger(__name__)


def handle_tool_errors(func):
    """Standardized error handling for agent tools at the tool-to-LLM boundary.

    Catches expected external service failures (AWS API errors, connection
    issues) and returns a clean ``[ERROR]`` prefixed string so the agent can
    communicate the failure conversationally. Programming errors (``TypeError``,
    ``KeyError``, etc.) are NOT caught — they propagate to Strands' error
    handling so they surface during development.

    This is an intentional exception to the "no bare except" code-quality
    rule. At the tool-to-LLM boundary, the "caller" is the model, not
    Python code. The ``[ERROR]`` prefix lets the agent (and trace analysis)
    distinguish failures from empty results.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (ClientError, BotoCoreError, EndpointConnectionError) as e:
            logger.error("%s failed: %s", func.__name__, e, exc_info=True)
            return f"[ERROR] {func.__name__} failed: {e}"

    return wrapper
