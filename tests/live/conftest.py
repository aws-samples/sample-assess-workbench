"""Live test configuration.

These tests hit real deployed AWS infrastructure via the CloudFront
distribution — the same path real users take. This validates the full
stack: WAF → CloudFront → API Gateway → Lambda.

Endpoint discovery:
  1. Env var override (API_ENDPOINT, WEBSOCKET_URL) — highest priority.
  2. CloudFront frontend_url from Terraform outputs — primary path.
     API: {frontend_url}/api, WebSocket: wss://{cloudfront_domain}/ws
  3. If neither is available, tests skip with a clear message.

Authentication:
  Most API routes require a Cognito JWT. Set these env vars for authenticated tests:
    TEST_USER_EMAIL    — Cognito user email
    TEST_USER_PASSWORD — Cognito user password
  Or they'll be auto-read from Terraform outputs where possible.
  Unauthenticated routes (like /health) work without credentials.

Review lifecycle:
  A session-scoped fixture creates a project, uploads a document, triggers a
  review, approves a 2-agent plan, and polls to completion. All review flow
  and WebSocket chat tests share this single project. Teardown deletes it.
"""
import os
import subprocess
import time
from pathlib import Path
import pytest
import requests
import boto3


# ---------------------------------------------------------------------------
# Endpoint discovery — CloudFront URL is the primary path
# ---------------------------------------------------------------------------

def _read_terraform_output(key: str) -> str:
    """Read a single Terraform output value. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["terraform", "output", "-raw", key],
            cwd=os.path.join(os.path.dirname(__file__), "..", "..", "terraform"),
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _discover(env_var: str, tf_key: str) -> str:
    """Resolve a config value: env var wins, then Terraform output."""
    return os.environ.get(env_var, "") or _read_terraform_output(tf_key)


def _resolve_endpoints() -> tuple[str, str]:
    """Resolve API and WebSocket endpoints.

    Priority:
      1. Explicit env vars (API_ENDPOINT, WEBSOCKET_URL) — for custom setups.
      2. CloudFront frontend_url from Terraform — the standard deployed path.
         API endpoint: {frontend_url}/api
         WebSocket URL: wss://{cloudfront_domain}/ws

    Returns:
        (api_endpoint, websocket_url) — either or both may be empty.
    """
    # Env var overrides take priority
    api = os.environ.get("API_ENDPOINT", "")
    ws = os.environ.get("WEBSOCKET_URL", "")

    if api and ws:
        return api, ws

    # Discover CloudFront URL from Terraform
    frontend_url = _read_terraform_output("frontend_url")

    if frontend_url:
        frontend_url = frontend_url.rstrip("/")
        if not api:
            # CloudFront proxies /api/* → /v1/* on API Gateway
            api = f"{frontend_url}/api"
        if not ws:
            # CloudFront proxies /ws → /{environment} on WebSocket API Gateway
            # Extract domain from https://xxx.cloudfront.net
            domain = frontend_url.replace("https://", "").replace("http://", "")
            ws = f"wss://{domain}/ws"

    return api, ws


# Resolve once at import time
API_ENDPOINT, WEBSOCKET_URL = _resolve_endpoints()


# ---------------------------------------------------------------------------
# Cognito auth — acquire a JWT for authenticated API calls
# ---------------------------------------------------------------------------

def _get_cognito_token() -> str:
    """Authenticate with Cognito and return an id_token.

    Requires TEST_USER_EMAIL and TEST_USER_PASSWORD env vars.
    Cognito client ID is read from Terraform outputs.
    Returns empty string if auth is not configured.
    """
    email = os.environ.get("TEST_USER_EMAIL", "")
    password = os.environ.get("TEST_USER_PASSWORD", "")
    client_id = _discover("COGNITO_CLIENT_ID", "cognito_client_id")

    if not all([email, password, client_id]):
        return ""

    try:
        region = os.environ.get("AWS_REGION", "us-west-2")
        client = boto3.client("cognito-idp", region_name=region)
        resp = client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password,
            },
        )
        return resp["AuthenticationResult"]["IdToken"]
    except Exception as e:
        print(f"  ⚠️  Cognito auth failed: {e}")
        return ""


# Cache token for the session (one login per test run)
_CACHED_TOKEN = None


def _get_cached_token() -> str:
    global _CACHED_TOKEN
    if _CACHED_TOKEN is None:
        _CACHED_TOKEN = _get_cognito_token()
    return _CACHED_TOKEN


# ---------------------------------------------------------------------------
# Session banner
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    """Mark all tests in this directory as live."""
    for item in items:
        if "/live/" in str(item.fspath):
            item.add_marker(pytest.mark.live)


def pytest_report_header(config):
    """Print a clear banner so the tester knows they're running against real AWS."""
    if not API_ENDPOINT and not WEBSOCKET_URL:
        return [
            "",
            "═" * 60,
            "  ⏭️  LIVE TESTS — SKIPPED (no endpoints configured)",
            "  Deploy first: task deploy",
            "  Or set API_ENDPOINT / WEBSOCKET_URL env vars",
            "═" * 60,
        ]
    lines = [
        "",
        "═" * 60,
        "  🔴 LIVE TESTS — hitting real AWS infrastructure",
    ]
    if API_ENDPOINT:
        lines.append(f"  HTTP API:   {API_ENDPOINT}")
    if WEBSOCKET_URL:
        lines.append(f"  WebSocket:  {WEBSOCKET_URL}")

    has_auth = bool(os.environ.get("TEST_USER_EMAIL"))
    lines.append(f"  Auth:       {'configured' if has_auth else 'NOT SET — authenticated tests will skip'}")
    lines.append("═" * 60)
    return lines


# ---------------------------------------------------------------------------
# Auto-skip when infrastructure is not available
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _require_live_infra():
    """Skip all live tests when no API endpoint is available."""
    if not API_ENDPOINT:
        pytest.skip(
            "LIVE TEST SKIPPED — no endpoint available. "
            "Deploy infra first (task deploy) or export API_ENDPOINT."
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_endpoint():
    """Base URL for the deployed HTTP API (no trailing slash)."""
    return API_ENDPOINT.rstrip("/")


@pytest.fixture(scope="session")
def websocket_url():
    """URL for the deployed WebSocket API."""
    if not WEBSOCKET_URL:
        pytest.skip("WEBSOCKET_URL not set — WebSocket tests skipped.")
    return WEBSOCKET_URL


@pytest.fixture(scope="session")
def auth_token():
    """Cognito id_token for authenticated API calls.

    Skips the test if credentials are not configured.
    """
    token = _get_cached_token()
    if not token:
        pytest.skip(
            "Auth not configured — set TEST_USER_EMAIL and TEST_USER_PASSWORD. "
            "See tests/README.md."
        )
    return token


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    """Authorization headers dict for authenticated requests."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="session")
def http(auth_headers):
    """HTTP helper that automatically includes auth headers.

    Usage in tests:
        resp = http.get(f"{api_endpoint}/projects")
        resp = http.post(f"{api_endpoint}/projects", payload={...})
    """
    def _get(url, **kwargs):
        headers = {**auth_headers, **kwargs.pop("headers", {})}
        return requests.get(url, headers=headers, timeout=30, **kwargs)

    def _post(url, payload=None, **kwargs):
        headers = {**auth_headers, **kwargs.pop("headers", {})}
        return requests.post(url, json=payload, headers=headers, timeout=30, **kwargs)

    def _put(url, payload=None, **kwargs):
        headers = {**auth_headers, **kwargs.pop("headers", {})}
        return requests.put(url, json=payload, headers=headers, timeout=30, **kwargs)

    def _delete(url, **kwargs):
        headers = {**auth_headers, **kwargs.pop("headers", {})}
        return requests.delete(url, headers=headers, timeout=30, **kwargs)

    class Http:
        get = staticmethod(_get)
        post = staticmethod(_post)
        put = staticmethod(_put)
        delete = staticmethod(_delete)

    return Http()


@pytest.fixture(scope="session")
def http_noauth():
    """HTTP helper without auth — for unauthenticated endpoints like /health."""
    def _get(url, **kwargs):
        return requests.get(url, timeout=30, **kwargs)

    class HttpNoAuth:
        get = staticmethod(_get)

    return HttpNoAuth()


# ---------------------------------------------------------------------------
# Review lifecycle fixture — shared across all live tests
# ---------------------------------------------------------------------------

REVIEW_TIMEOUT_S = 300
POLL_INTERVAL_S = 5
TXT_DOC = Path(__file__).parent.parent.parent / "test-docs" / "sample-design.txt"


class ReviewLifecycleError(Exception):
    """Raised when a specific lifecycle step fails, with diagnostic detail."""

    def __init__(self, step: str, detail: str):
        self.step = step
        self.detail = detail
        super().__init__(f"[{step}] {detail}")


def _run_review_lifecycle(api: str, http_helper) -> dict:
    """Drive a full review lifecycle and return the result.

    Creates a project, uploads a document, triggers a review, approves a
    2-agent sequential plan, and polls to completion. Returns a dict with
    all identifiers and the completed project response.

    Each step raises ReviewLifecycleError with a specific message on failure
    so test output clearly identifies which step broke and why.

    Args:
        api: Base API URL (no trailing slash).
        http_helper: Authenticated HTTP helper with get/post/put/delete.

    Returns:
        Dict with keys: project_id, review_id, completed_project.

    Raises:
        ReviewLifecycleError: On any step failure, with step name and detail.
    """
    # 1. Create project
    resp = http_helper.post(f"{api}/projects", payload={
        "name": "E2E Test — review lifecycle",
        "description": "Automated test, will be deleted.",
        "files": [{"filename": "sample-design.txt"}],
    })
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

    # 2. Upload document
    if not TXT_DOC.exists():
        raise ReviewLifecycleError("upload_document", f"Test doc not found: {TXT_DOC}")
    doc_bytes = TXT_DOC.read_bytes()
    resp = requests.put(upload_url, data=doc_bytes,
                        headers={"Content-Type": "application/octet-stream"}, timeout=30)
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
    deadline = time.time() + REVIEW_TIMEOUT_S
    last_code, last_status, polls = None, None, 0
    while time.time() < deadline:
        url = f"{api}/projects/{project_id}/reviews/{review_id}/plan"
        resp = http_helper.get(url)
        last_code = resp.status_code
        polls += 1
        if resp.status_code == 200:
            plan_data = resp.json()
            last_status = plan_data.get("status")
            if last_status == "pending_approval":
                print(f"   ✓ Plan ready after {polls} polls")
                break
        time.sleep(POLL_INTERVAL_S)
    else:
        raise ReviewLifecycleError(
            "poll_for_plan",
            f"Plan not ready after {polls} polls ({REVIEW_TIMEOUT_S}s). "
            f"Last HTTP {last_code}, status: {last_status}",
        )

    # 5. Approve with 2-agent sequential plan (architecture → security)
    judge_off = {"enabled": False, "max_iterations": 1, "quality_threshold": 0.5}
    plan_body = {
        **{k: v for k, v in plan_data.get("plan", {}).items() if k != "groups"},
        "groups": [
            {"agents": [{"agent_type": "architecture", "depth": "quick", "judge": judge_off}]},
            {"agents": [{"agent_type": "security", "depth": "quick", "judge": judge_off}]},
        ],
    }
    url = f"{api}/projects/{project_id}/reviews/{review_id}/approve"
    resp = http_helper.post(url, payload={"plan": plan_body})
    if resp.status_code != 200:
        raise ReviewLifecycleError("approve_plan", f"HTTP {resp.status_code}: {resp.text}")
    print("   ✓ Approved: 2-agent sequential plan (architecture → security)")

    # 6. Poll for completion
    deadline = time.time() + REVIEW_TIMEOUT_S
    last_status, polls = None, 0
    while time.time() < deadline:
        resp = http_helper.get(f"{api}/projects/{project_id}")
        polls += 1
        if resp.status_code == 200:
            project = resp.json()
            last_status = project["status"]
            if last_status in ("completed", "failed"):
                print(f"   ✓ Review {last_status} after {polls} polls")
                break
        time.sleep(POLL_INTERVAL_S)
    else:
        raise ReviewLifecycleError(
            "poll_for_completion",
            f"Review not done after {polls} polls ({REVIEW_TIMEOUT_S}s). "
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


# Cached lifecycle result — computed once per session
_lifecycle_result: dict | None = None
_lifecycle_error: ReviewLifecycleError | None = None


@pytest.fixture(scope="session")
def review_lifecycle(api_endpoint, http):
    """Session-scoped fixture: run a full review lifecycle once, share the result.

    Creates a project, runs a 2-agent review to completion, and yields the
    result dict. Deletes the project on teardown.

    If the lifecycle fails, stores the error so dependent tests get a clear
    skip message identifying which step failed.
    """
    global _lifecycle_result, _lifecycle_error

    if _lifecycle_error:
        pytest.skip(f"Review lifecycle failed: {_lifecycle_error}")
    if _lifecycle_result:
        yield _lifecycle_result
        return

    print("\n" + "─" * 60)
    print("  Setting up review lifecycle...")
    print("─" * 60)

    project_id = None
    try:
        result = _run_review_lifecycle(api_endpoint, http)
        _lifecycle_result = result
        project_id = result["project_id"]
        yield result
    except ReviewLifecycleError as e:
        _lifecycle_error = e
        pytest.fail(f"Review lifecycle setup failed at [{e.step}]: {e.detail}")
    finally:
        if project_id:
            print(f"\n   Cleaning up project {project_id}...")
            try:
                http.delete(f"{api_endpoint}/projects/{project_id}")
                print(f"   ✓ Deleted project {project_id}")
            except Exception as e:
                print(f"   ⚠️  Cleanup failed: {e}")
