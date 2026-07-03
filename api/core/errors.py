"""Shared error message extraction for workflow error handlers.

Used by update_status_failed and post_completion_error Lambdas to parse
Step Functions Catch error payloads into human-readable messages.
"""

import json

DEFAULT_MAX_LENGTH = 1000


def extract_error_message(raw_error, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    """Extract a human-readable error message from a Step Functions error payload.

    Handles the various shapes that Step Functions Catch blocks produce:
    string errors, dicts with Error/Cause keys, and arbitrary objects.
    Truncates to max_length to prevent oversized DynamoDB writes.

    Args:
        raw_error: Error object from Step Functions Catch — may be a string,
            dict with Error/Cause keys, or other structure.
        max_length: Maximum length of the returned message.

    Returns:
        Truncated error message string.
    """
    if isinstance(raw_error, str):
        return raw_error[:max_length]

    if isinstance(raw_error, dict):
        error_type = raw_error.get("Error", "")
        cause = raw_error.get("Cause", "")
        if error_type and cause:
            msg = f"{error_type}: {cause}"
        elif error_type:
            msg = error_type
        elif cause:
            msg = cause
        else:
            try:
                msg = json.dumps(raw_error, default=str)
            except Exception:
                msg = str(raw_error)
        return msg[:max_length]

    return str(raw_error)[:max_length]
