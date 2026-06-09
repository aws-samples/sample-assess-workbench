"""Live tests for the HTTP API.

These tests hit the real deployed API Gateway. They verify the API contract
defined in api/openapi.yaml — response shapes, status codes, required fields.

Authentication:
  /health is unauthenticated — always runs if API_ENDPOINT is set.
  All other routes require Cognito JWT — set TEST_USER_EMAIL and
  TEST_USER_PASSWORD env vars. Tests skip gracefully without them.

Tests are ordered to form a natural lifecycle:
  health → list → create → get → delete
"""
import pytest


pytestmark = pytest.mark.live


# ═══════════════════════════════════════════════════════════════════════════
# Health (unauthenticated)
# ═══════════════════════════════════════════════════════════════════════════

class TestHealth:

    def test_health_returns_200_with_status(self, api_endpoint, http_noauth):
        """GET /health should return 200 with a 'status' field (no auth required)."""
        resp = http_noauth.get(f"{api_endpoint}/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "timestamp" in body


# ═══════════════════════════════════════════════════════════════════════════
# Agents & Models (authenticated, read-only)
# ═══════════════════════════════════════════════════════════════════════════

class TestReferenceData:

    def test_list_agents_returns_array(self, api_endpoint, http):
        """GET /agents should return an array of agent definitions with all display fields."""
        resp = http.get(f"{api_endpoint}/agents")

        assert resp.status_code == 200
        body = resp.json()
        assert "agents" in body
        assert isinstance(body["agents"], list)
        assert len(body["agents"]) > 0, "Agent registry is empty — run task deploy:seed"

        for agent in body["agents"]:
            assert "agent_type" in agent, f"Missing agent_type: {agent}"
            assert "display_name" in agent, f"Missing display_name: {agent.get('agent_type')}"
            assert "enabled" in agent, f"Missing enabled: {agent.get('agent_type')}"
            assert "icon" in agent and agent["icon"], f"Missing/empty icon: {agent.get('agent_type')}"
            assert "color" in agent and agent["color"], f"Missing/empty color: {agent.get('agent_type')}"

    def test_list_models_returns_array(self, api_endpoint, http):
        """GET /models should return available Bedrock models."""
        resp = http.get(f"{api_endpoint}/models")

        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body
        assert isinstance(body["models"], list)


# ═══════════════════════════════════════════════════════════════════════════
# Projects — list (authenticated, read-only)
# ═══════════════════════════════════════════════════════════════════════════

class TestProjectList:

    def test_list_projects_returns_200(self, api_endpoint, http):
        """GET /projects should return 200 with a projects array."""
        resp = http.get(f"{api_endpoint}/projects")

        assert resp.status_code == 200
        body = resp.json()
        assert "projects" in body
        assert isinstance(body["projects"], list)
        assert "count" in body

    def test_list_projects_with_status_filter(self, api_endpoint, http):
        """GET /projects?status=completed should filter by status."""
        resp = http.get(f"{api_endpoint}/projects", params={"status": "completed"})

        assert resp.status_code == 200
        body = resp.json()
        for project in body["projects"]:
            assert project["status"] == "completed"

    def test_list_projects_with_limit(self, api_endpoint, http):
        """GET /projects?limit=2 should respect the limit."""
        resp = http.get(f"{api_endpoint}/projects", params={"limit": "2"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["projects"]) <= 2


# ═══════════════════════════════════════════════════════════════════════════
# Projects — create / get / delete lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestProjectLifecycle:
    """These tests create a real project, verify it, then clean it up.
    They run against the live API and leave no residual data."""

    def test_create_get_delete_project(self, api_endpoint, http):
        """Full lifecycle: create a project, read it back, then delete it."""

        # --- Create ---
        create_resp = http.post(f"{api_endpoint}/projects", payload={
            "name": "Test Project — automated test",
            "description": "Created by test_http_api.py, will be deleted immediately.",
            "files": [{"filename": "test-document.pdf"}],
        })
        assert create_resp.status_code == 201, (
            f"Expected 201, got {create_resp.status_code}: {create_resp.text}"
        )

        created = create_resp.json()
        project_id = created["project_id"]
        assert created["name"] == "Test Project — automated test"
        assert created["status"] == "pending"
        assert "upload_urls" in created

        # --- Read back ---
        get_resp = http.get(f"{api_endpoint}/projects/{project_id}")
        assert get_resp.status_code == 200

        project = get_resp.json()
        assert project["project_id"] == project_id
        assert project["status"] == "pending"

        # --- Delete ---
        del_resp = http.delete(f"{api_endpoint}/projects/{project_id}")
        assert del_resp.status_code == 200

        deleted = del_resp.json()
        assert deleted["project_id"] == project_id

        # --- Confirm gone ---
        gone_resp = http.get(f"{api_endpoint}/projects/{project_id}")
        assert gone_resp.status_code == 404

    def test_create_project_without_name_returns_400(self, api_endpoint, http):
        """POST /projects with no name should return 400."""
        resp = http.post(f"{api_endpoint}/projects", payload={
            "description": "Missing the required name field",
        })
        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body


# ═══════════════════════════════════════════════════════════════════════════
# Not found
# ═══════════════════════════════════════════════════════════════════════════

class TestNotFound:

    def test_get_nonexistent_project_returns_404(self, api_endpoint, http):
        """GET /projects/{id} for a non-existent ID should return 404."""
        resp = http.get(f"{api_endpoint}/projects/nonexistent-id-12345")
        assert resp.status_code == 404

    def test_delete_nonexistent_project_returns_404(self, api_endpoint, http):
        """DELETE /projects/{id} for a non-existent ID should return 404."""
        resp = http.delete(f"{api_endpoint}/projects/nonexistent-id-12345")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Analytics (authenticated, read-only)
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalytics:

    def test_analytics_summary_returns_200(self, api_endpoint, http):
        """GET /analytics/summary should return aggregated quality data."""
        resp = http.get(f"{api_endpoint}/analytics/summary")

        assert resp.status_code == 200
        body = resp.json()
        assert "review_count" in body

    def test_analytics_trends_returns_200(self, api_endpoint, http):
        """GET /analytics/trends should return time-series data."""
        resp = http.get(f"{api_endpoint}/analytics/trends")

        assert resp.status_code == 200
        body = resp.json()
        assert "data_points" in body


# ═══════════════════════════════════════════════════════════════════════════
# Contexts — create / get / delete lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestContextLifecycle:
    """CRUD lifecycle for organizational context documents.
    Self-cleaning — creates a context, verifies it, then deletes it."""

    def test_create_get_delete_context(self, api_endpoint, http):
        """Full lifecycle: create a context, list it, read it back, then delete it."""

        # --- Create ---
        create_resp = http.post(f"{api_endpoint}/contexts", payload={
            "name": "Test Context — automated test",
            "description": "Created by test_http_api.py, will be deleted immediately.",
        })
        assert create_resp.status_code == 201, (
            f"Expected 201, got {create_resp.status_code}: {create_resp.text}"
        )

        created = create_resp.json()
        context_id = created["context_id"]
        assert created["name"] == "Test Context — automated test"
        assert "upload_url" in created

        # --- List (should include the new context) ---
        list_resp = http.get(f"{api_endpoint}/contexts")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert "contexts" in body
        context_ids = [c["context_id"] for c in body["contexts"]]
        assert context_id in context_ids, "New context not in list"

        # --- Read back ---
        get_resp = http.get(f"{api_endpoint}/contexts/{context_id}")
        assert get_resp.status_code == 200
        context = get_resp.json()
        assert context["context_id"] == context_id

        # --- Delete ---
        del_resp = http.delete(f"{api_endpoint}/contexts/{context_id}")
        assert del_resp.status_code == 200
        deleted = del_resp.json()
        assert deleted["context_id"] == context_id

        # --- Confirm gone ---
        gone_resp = http.get(f"{api_endpoint}/contexts/{context_id}")
        assert gone_resp.status_code == 404

    def test_get_nonexistent_context_returns_404(self, api_endpoint, http):
        """GET /contexts/{id} for a non-existent ID should return 404."""
        resp = http.get(f"{api_endpoint}/contexts/nonexistent-ctx-12345")
        assert resp.status_code == 404

    def test_delete_nonexistent_context_returns_404(self, api_endpoint, http):
        """DELETE /contexts/{id} for a non-existent ID should return 404."""
        resp = http.delete(f"{api_endpoint}/contexts/nonexistent-ctx-12345")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Auth enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthEnforcement:

    def test_unauthenticated_request_returns_401(self, api_endpoint, http_noauth):
        """GET /projects without auth should return 401."""
        resp = http_noauth.get(f"{api_endpoint}/projects")
        assert resp.status_code == 401
