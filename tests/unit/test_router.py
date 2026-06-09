"""Unit tests for the API route matching logic.

Source: api/rest_api/lambda_handler.py (_compile_route pattern)
Contract: path templates like '/projects/{project_id}' compile to regexes
          that match paths and extract named parameters.

The lambda_handler module can't be imported in a test environment because it
initialises boto3 clients and pulls in Lambda-layer modules at import time.
Instead, we replicate the two pure functions (_compile_route and _resolve_route)
and test the pattern-matching logic directly. This is the same regex code that
runs in production — just without the handler wiring.
"""
import re

# ---------------------------------------------------------------------------
# Replicated from lambda_handler.py — pure regex, no AWS dependencies
# ---------------------------------------------------------------------------

def _compile_route(pattern: str):
    """Convert '/projects/{project_id}' → compiled regex with named groups."""
    regex = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', pattern)
    return re.compile(f'^{regex}$')


# A representative subset of the production route table (method, pattern)
ROUTE_TABLE = [
    ("GET",    "/health"),
    ("GET",    "/agents"),
    ("GET",    "/models"),
    ("POST",   "/projects"),
    ("GET",    "/projects"),
    ("GET",    "/projects/{project_id}"),
    ("DELETE", "/projects/{project_id}"),
    ("GET",    "/projects/{project_id}/document"),
    ("POST",   "/projects/{project_id}/review"),
    ("GET",    "/projects/{project_id}/reviews/{review_id}/plan"),
    ("POST",   "/projects/{project_id}/reviews/{review_id}/approve"),
    ("POST",   "/projects/{project_id}/reviews/{review_id}/reject"),
    ("POST",   "/projects/{project_id}/feedback"),
    ("GET",    "/projects/{project_id}/feedback"),
    ("POST",   "/contexts"),
    ("GET",    "/contexts"),
    ("GET",    "/contexts/{context_id}"),
    ("DELETE", "/contexts/{context_id}"),
    ("GET",    "/analytics/summary"),
    ("GET",    "/analytics/trends"),
    ("GET",    "/analytics/coverage/{project_id}"),
    ("GET",    "/admin/registry"),
    ("PUT",    "/admin/registry/{agent_type}"),
]

COMPILED_ROUTES = [
    (method, _compile_route(pattern), pattern)
    for method, pattern in ROUTE_TABLE
]


def _resolve(method: str, path: str):
    """Match method + path against the compiled route table.

    Returns (matched_pattern, params_dict) or (None, None).
    """
    for route_method, compiled, pattern in COMPILED_ROUTES:
        if route_method != method:
            continue
        match = compiled.match(path)
        if match:
            return pattern, match.groupdict()
    return None, None


# ═══════════════════════════════════════════════════════════════════════════
# Exact path matching
# ═══════════════════════════════════════════════════════════════════════════

class TestExactRoutes:
    """Routes with no path parameters should match exactly."""

    def test_health(self):
        pattern, params = _resolve("GET", "/health")
        assert pattern == "/health"
        assert params == {}

    def test_list_projects(self):
        pattern, _ = _resolve("GET", "/projects")
        assert pattern == "/projects"

    def test_create_project(self):
        pattern, _ = _resolve("POST", "/projects")
        assert pattern == "/projects"

    def test_analytics_summary(self):
        pattern, _ = _resolve("GET", "/analytics/summary")
        assert pattern == "/analytics/summary"


# ═══════════════════════════════════════════════════════════════════════════
# Path parameter extraction
# ═══════════════════════════════════════════════════════════════════════════

class TestPathParameters:
    """Parameterised routes should extract named groups from the URL."""

    def test_single_param(self):
        _, params = _resolve("GET", "/projects/abc123")
        assert params == {"project_id": "abc123"}

    def test_delete_extracts_id(self):
        _, params = _resolve("DELETE", "/projects/proj-99")
        assert params == {"project_id": "proj-99"}

    def test_nested_resource(self):
        _, params = _resolve("GET", "/projects/p1/document")
        assert params == {"project_id": "p1"}

    def test_two_params(self):
        _, params = _resolve("GET", "/projects/p1/reviews/r2/plan")
        assert params == {"project_id": "p1", "review_id": "r2"}

    def test_approve_extracts_both_ids(self):
        _, params = _resolve("POST", "/projects/p1/reviews/r2/approve")
        assert params == {"project_id": "p1", "review_id": "r2"}

    def test_analytics_coverage(self):
        _, params = _resolve("GET", "/analytics/coverage/p1")
        assert params == {"project_id": "p1"}

    def test_admin_registry_update(self):
        _, params = _resolve("PUT", "/admin/registry/architecture")
        assert params == {"agent_type": "architecture"}

    def test_context_by_id(self):
        _, params = _resolve("GET", "/contexts/ctx-abc")
        assert params == {"context_id": "ctx-abc"}


# ═══════════════════════════════════════════════════════════════════════════
# Non-matches
# ═══════════════════════════════════════════════════════════════════════════

class TestNonMatches:
    """Requests that don't match any route should return (None, None)."""

    def test_unknown_path(self):
        pattern, _ = _resolve("GET", "/nonexistent")
        assert pattern is None

    def test_wrong_method(self):
        pattern, _ = _resolve("DELETE", "/health")
        assert pattern is None

    def test_post_to_get_only(self):
        pattern, _ = _resolve("POST", "/analytics/summary")
        assert pattern is None

    def test_trailing_segment_no_match(self):
        pattern, _ = _resolve("GET", "/projects/abc/unknown")
        assert pattern is None

    def test_trailing_slash_no_match(self):
        pattern, _ = _resolve("GET", "/health/")
        assert pattern is None
