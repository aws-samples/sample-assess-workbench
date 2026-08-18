"""Shared review-lifecycle driver.

Drives a full review against the deployed HTTP API the same way a real user
would: create a project, upload a document, trigger a review, approve a plan,
and poll to completion. Both the live test suite (``tests/live/conftest.py``)
and the demo seeder import this module, so they exercise one code path instead
of two divergent copies.

This module ships publicly with the test suite, so its default document is the
public fixture ``tests/fixtures/sample-design.txt`` — never an internal corpus.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol, TypedDict

import requests

# --- Tunables ---------------------------------------------------------------

REVIEW_TIMEOUT_S = 300
POLL_INTERVAL_S = 5

# Public fixture shipped with the test suite. The seeder overrides doc_path with
# an internal corpus document; the default stays public so a stock clone runs.
DEFAULT_DOC = Path(__file__).parent.parent / "fixtures" / "sample-design.txt"
DEFAULT_FILENAME = "sample-design.txt"
DEFAULT_PROJECT_NAME = "E2E Test — review lifecycle"
DEFAULT_PROJECT_DESCRIPTION = "Automated test, will be deleted."

# Judge disabled: keeps the default lifecycle fast and deterministic.
JUDGE_OFF: dict[str, Any] = {"enabled": False, "max_iterations": 1, "quality_threshold": 0.5}


class HttpHelper(Protocol):
    """Authenticated HTTP client contract — see conftest's ``http`` fixture.

    Methods mirror the subset of ``requests`` the lifecycle uses; ``post``/``put``
    take the JSON body as ``payload`` and inject auth headers.
    """

    def get(self, url: str, **kwargs: Any) -> requests.Response: ...
    def post(
        self, url: str, payload: dict[str, Any] | None = ..., **kwargs: Any
    ) -> requests.Response: ...
    def put(
        self, url: str, payload: dict[str, Any] | None = ..., **kwargs: Any
    ) -> requests.Response: ...
    def delete(self, url: str, **kwargs: Any) -> requests.Response: ...


class LifecycleResult(TypedDict):
    """Return shape of :func:`run_review_lifecycle`."""

    project_id: str
    review_id: str
    completed_project: dict[str, Any]


class ReviewLifecycleError(Exception):
    """Raised when a specific lifecycle step fails, with diagnostic detail.

    Attributes:
        step: The lifecycle step that failed (e.g. ``"create_project"``).
        detail: Human-readable failure detail (status code, body, etc.).
    """

    def __init__(self, step: str, detail: str) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"[{step}] {detail}")


def build_groups(
    sequence: list[list[str]],
    *,
    depth: str = "quick",
    judge: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build review-plan ``groups`` from a sequence of agent-type lists.

    Each inner list is one group: agents within a group run in parallel, and the
    groups themselves run sequentially in order. For example::

        build_groups([["architecture"], ["security"]])   # arch, then security
        build_groups([["architecture", "security"]])      # both, in parallel

    Args:
        sequence: Ordered groups, each a list of ``agent_type`` strings.
        depth: Review depth applied to every agent (e.g. ``"quick"``,
            ``"standard"``).
        judge: Judge config applied to every agent; defaults to
            :data:`JUDGE_OFF` (judge disabled).

    Returns:
        A list of group dicts shaped for the approve endpoint's ``groups`` field.
    """
    judge_cfg = JUDGE_OFF if judge is None else judge
    return [
        {"agents": [{"agent_type": at, "depth": depth, "judge": judge_cfg} for at in group]}
        for group in sequence
    ]


# Default plan reproduces the original live-test behavior: architecture then
# security, sequential, judge disabled.
DEFAULT_PLAN_GROUPS = build_groups([["architecture"], ["security"]])


def run_review_lifecycle(
    api: str,
    http_helper: HttpHelper,
    *,
    doc_path: Path = DEFAULT_DOC,
    filename: str = DEFAULT_FILENAME,
    project_name: str = DEFAULT_PROJECT_NAME,
    project_description: str = DEFAULT_PROJECT_DESCRIPTION,
    plan_groups: list[dict[str, Any]] | None = None,
    timeout_s: int = REVIEW_TIMEOUT_S,
    poll_interval_s: int = POLL_INTERVAL_S,
) -> LifecycleResult:
    """Drive a full review lifecycle and return the result.

    Creates a project, uploads ``doc_path``, triggers a review, approves the
    plan defined by ``plan_groups``, and polls to completion. Each step raises
    :class:`ReviewLifecycleError` with a specific message on failure so callers
    can identify exactly which step broke and why.

    Args:
        api: Base API URL (no trailing slash).
        http_helper: Authenticated HTTP helper with ``get``/``post``/``put``/
            ``delete``.
        doc_path: Local path to the document to upload. Defaults to the public
            ``sample-design.txt`` fixture.
        filename: Filename registered with the project (the upload basename).
        project_name: Project display name.
        project_description: Project description.
        plan_groups: Review-plan groups (see :func:`build_groups`). Defaults to
            :data:`DEFAULT_PLAN_GROUPS` (architecture → security, judge off).
        timeout_s: Per-poll-phase timeout in seconds (plan, then completion).
        poll_interval_s: Delay between polls in seconds.

    Returns:
        A :class:`LifecycleResult` with ``project_id``, ``review_id``, and the
        completed project response.

    Raises:
        ReviewLifecycleError: On any step failure, with step name and detail.
    """
    groups = DEFAULT_PLAN_GROUPS if plan_groups is None else plan_groups

    # 1. Create project
    resp = http_helper.post(
        f"{api}/projects",
        payload={
            "name": project_name,
            "description": project_description,
            "files": [{"filename": filename}],
        },
    )
    if resp.status_code != 201:
        raise ReviewLifecycleError("create_project", f"HTTP {resp.status_code}: {resp.text}")
    created = resp.json()
    project_id = created["project_id"]
    urls = created.get("upload_urls", [])
    if not urls:
        raise ReviewLifecycleError("create_project", "No upload_urls in response")
    upload_url = urls[0].get("upload_url")
    if not upload_url:
        raise ReviewLifecycleError("create_project", "upload_url missing from upload_urls entry")
    print(f"   ✓ Created project: {project_id}")

    # 2. Upload document (presigned S3 PUT — no auth header)
    if not doc_path.exists():
        raise ReviewLifecycleError("upload_document", f"Document not found: {doc_path}")
    doc_bytes = doc_path.read_bytes()
    resp = requests.put(
        upload_url, data=doc_bytes, headers={"Content-Type": "application/octet-stream"}, timeout=30
    )
    if resp.status_code != 200:
        raise ReviewLifecycleError("upload_document", f"HTTP {resp.status_code}: {resp.text}")
    print(f"   ✓ Uploaded document: {len(doc_bytes)} bytes")

    # 3. Trigger review
    resp = http_helper.post(f"{api}/projects/{project_id}/review")
    if resp.status_code != 202:
        raise ReviewLifecycleError("trigger_review", f"HTTP {resp.status_code}: {resp.text}")
    review_id = resp.json()["review_id"]
    print(f"   ✓ Triggered review: {review_id}")

    # 4. Poll for plan
    deadline = time.time() + timeout_s
    last_code, last_status, polls, transient = None, None, 0, 0
    plan_data: dict[str, Any] = {}
    while time.time() < deadline:
        polls += 1
        url = f"{api}/projects/{project_id}/reviews/{review_id}/plan"
        try:
            resp = http_helper.get(url)
        except requests.exceptions.RequestException as e:
            # Transient transport error while the backend is working — keep
            # polling within the deadline rather than aborting the wait.
            transient += 1
            print(f"   … plan poll {polls}: transient {e.__class__.__name__}, retrying")
            time.sleep(poll_interval_s)
            continue
        last_code = resp.status_code
        if resp.status_code == 200:
            plan_data = resp.json()
            last_status = plan_data.get("status")
            if last_status == "pending_approval":
                print(f"   ✓ Plan ready after {polls} polls")
                break
        time.sleep(poll_interval_s)
    else:
        raise ReviewLifecycleError(
            "poll_for_plan",
            f"Plan not ready after {polls} polls ({timeout_s}s, {transient} transient errors). "
            f"Last HTTP {last_code}, status: {last_status}",
        )

    # 5. Approve with the requested plan groups
    plan_body = {
        **{k: v for k, v in plan_data.get("plan", {}).items() if k != "groups"},
        "groups": groups,
    }
    url = f"{api}/projects/{project_id}/reviews/{review_id}/approve"
    resp = http_helper.post(url, payload={"plan": plan_body})
    if resp.status_code != 200:
        raise ReviewLifecycleError("approve_plan", f"HTTP {resp.status_code}: {resp.text}")
    print(f"   ✓ Approved plan: {len(groups)} group(s)")

    # 6. Poll for completion
    deadline = time.time() + timeout_s
    last_status, polls, transient = None, 0, 0
    project: dict[str, Any] = {}
    while time.time() < deadline:
        polls += 1
        try:
            resp = http_helper.get(f"{api}/projects/{project_id}")
        except requests.exceptions.RequestException as e:
            # Transient transport error while the review runs — keep polling
            # within the deadline rather than aborting the wait.
            transient += 1
            print(f"   … completion poll {polls}: transient {e.__class__.__name__}, retrying")
            time.sleep(poll_interval_s)
            continue
        if resp.status_code == 200:
            project = resp.json()
            last_status = project["status"]
            if last_status in ("completed", "failed"):
                print(f"   ✓ Review {last_status} after {polls} polls")
                break
        time.sleep(poll_interval_s)
    else:
        raise ReviewLifecycleError(
            "poll_for_completion",
            f"Review not done after {polls} polls ({timeout_s}s, {transient} transient errors). "
            f"Last status: {last_status}",
        )

    if last_status == "failed":
        error_msg = project.get("error_message", "unknown")
        raise ReviewLifecycleError("review_failed", f"Review failed: {error_msg}")

    # 7. Verify review data is present
    review = project.get("review")
    if not review:
        raise ReviewLifecycleError(
            "verify_review_data",
            "Status is 'completed' but GET /projects/{id} has no 'review' field. "
            "Check store_results Lambda and get_latest_review().",
        )

    return {
        "project_id": project_id,
        "review_id": review_id,
        "completed_project": project,
    }
