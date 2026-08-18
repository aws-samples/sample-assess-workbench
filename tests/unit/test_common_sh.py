"""Contract tests for pure-logic helpers in scripts/common.sh.

common.sh is a function library (no top-level execution), so it can be sourced
in isolation and its helpers exercised directly. These cover is_not_found, the
shared predicate the teardown scripts use to keep "already gone" quiet while
failing loud on real errors — getting it wrong either masks a real failure or
turns an idempotent re-run into a spurious error.

Offline: no AWS, no .env.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMON_SH = REPO_ROOT / "scripts" / "common.sh"


def _is_not_found(error_text: str) -> bool:
    """Source common.sh and report whether is_not_found matches the given text.

    Returns:
        True if the helper treats the text as a missing-resource (exit 0).
    """
    script = f"source {shlex.quote(str(COMMON_SH))}\nis_not_found {shlex.quote(error_text)}\n"
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    return result.returncode == 0


class TestIsNotFound:
    # Real AWS CLI error fragments that mean "already gone" → idempotent success.
    MISSING = [
        "An error occurred (ResourceNotFoundException) when calling the DeleteMemory operation",
        "An error occurred (NoSuchBucket) when calling the DeleteBucket operation",
        "NoSuchEntity: The role does not exist",
        "An error occurred (NotFoundException) when calling the DeleteIndex operation",
        "Knowledge base could not be found",
    ]

    # Real failures that must NOT be swallowed.
    REAL_FAILURES = [
        "An error occurred (AccessDeniedException) when calling the DeleteBucket operation",
        "An error occurred (ConflictException): operation in progress",
        "An error occurred (ThrottlingException): rate exceeded",
        "An error occurred (ValidationException): invalid identifier",
    ]

    def test_missing_resource_errors_match(self) -> None:
        for err in self.MISSING:
            assert _is_not_found(err), f"should treat as already-gone: {err!r}"

    def test_real_failures_do_not_match(self) -> None:
        for err in self.REAL_FAILURES:
            assert not _is_not_found(err), f"should NOT swallow real failure: {err!r}"

    def test_empty_string_is_not_a_missing_resource(self) -> None:
        # An empty error string is not evidence the resource was absent.
        assert not _is_not_found("")
