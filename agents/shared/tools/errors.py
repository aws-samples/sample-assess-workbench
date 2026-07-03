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

# AWS error codes that indicate a broken deployment — a missing IAM permission,
# bad/expired credentials, or a misconfigured resource — rather than an
# expected, transient external failure. These MUST NOT be swallowed into a soft
# ``[ERROR]`` string: doing so lets a review complete with unverifiable findings
# (the agent silently falls back to training knowledge) while the real fault —
# e.g. the agent role lacking ``bedrock:Retrieve`` — stays invisible. They
# propagate so the run fails loudly and an operator fixes the configuration.
_FAIL_LOUD_ERROR_CODES = frozenset(
    {
        "AccessDeniedException",
        "AccessDenied",
        "UnauthorizedException",
        "UnrecognizedClientException",
        "InvalidSignatureException",
        "ExpiredTokenException",
    }
)


def handle_tool_errors(func):
    """Standardized error handling for agent tools at the tool-to-LLM boundary.

    Catches *expected* external service failures (transient AWS API errors,
    connection issues) and returns a clean ``[ERROR]`` prefixed string so the
    agent can communicate the failure conversationally.

    Two classes of error are deliberately NOT swallowed:

    - Programming errors (``TypeError``, ``KeyError``, etc.) — never caught here;
      they propagate to Strands' error handling so they surface in development.
    - Authorization / configuration errors (:data:`_FAIL_LOUD_ERROR_CODES`, e.g.
      ``AccessDeniedException``) — re-raised rather than returned as ``[ERROR]``.
      These are deployment faults, not conversational failures; swallowing them
      would let the review produce unverified findings while hiding a broken
      IAM/config state.

    This is an intentional exception to the "no bare except" code-quality rule:
    at the tool-to-LLM boundary the "caller" is the model, not Python code, so
    transient failures are reported as data. Config faults are not.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in _FAIL_LOUD_ERROR_CODES:
                logger.error(
                    "%s hit non-recoverable %s — propagating (deployment misconfig): %s",
                    func.__name__,
                    error_code,
                    e,
                    exc_info=True,
                )
                raise
            logger.error("%s failed: %s", func.__name__, e, exc_info=True)
            return f"[ERROR] {func.__name__} failed: {e}"
        except (BotoCoreError, EndpointConnectionError) as e:
            logger.error("%s failed: %s", func.__name__, e, exc_info=True)
            return f"[ERROR] {func.__name__} failed: {e}"

    return wrapper
