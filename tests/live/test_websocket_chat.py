"""Live tests for WebSocket chat API.

These tests connect to the real deployed WebSocket API Gateway and exchange
messages with deployed AgentCore chat agents. They use the session-scoped
``review_lifecycle`` fixture from conftest.py — no external TEST_PROJECT_ID
needed.

Requirements:
  - Deployed infrastructure (task deploy)
  - WEBSOCKET_URL set (auto-discovered from Terraform or env var)
  - TEST_USER_EMAIL + TEST_USER_PASSWORD for Cognito auth
"""

import json
from uuid import uuid4
import pytest

try:
    import websockets

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not WEBSOCKETS_AVAILABLE, reason="websockets not installed"),
]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_connects_and_disconnects(websocket_url, auth_token):
    """A basic connection to the WebSocket API should succeed."""
    async with websockets.connect(f"{websocket_url}?token={auth_token}") as ws:
        assert not ws.close_code, "Connection should be open"


# ---------------------------------------------------------------------------
# Agent chat — happy path
# ---------------------------------------------------------------------------


async def _chat_round_trip(ws_url, token, agent, message, project_id):
    """Send a message and collect the full streamed response.

    Returns (chunks, full_response) so callers can assert on both.
    """
    async with websockets.connect(f"{ws_url}?token={token}") as ws:
        await ws.send(
            json.dumps(
                {
                    "action": "sendMessage",
                    "projectId": project_id,
                    "agent": agent,
                    "message": message,
                    "sessionId": str(uuid4()),
                }
            )
        )

        chunks = []
        full_response = None

        async for raw in ws:
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "chunk":
                chunks.append(data["content"])
            elif msg_type == "complete":
                full_response = data["fullResponse"]
                break
            elif msg_type == "error":
                pytest.fail(f"Agent returned error: {data['error']}")

        return chunks, full_response


@pytest.mark.asyncio
async def test_security_agent_responds(websocket_url, auth_token, review_lifecycle):
    """Security agent should return a streamed response with at least one chunk."""
    project_id = review_lifecycle["project_id"]
    chunks, full = await _chat_round_trip(
        websocket_url,
        auth_token,
        "security",
        "What are the top 3 security concerns?",
        project_id,
    )
    assert len(chunks) > 0, "Expected at least one streamed chunk"
    assert full and len(full) > 0, "Expected a non-empty complete response"


# ---------------------------------------------------------------------------
# Validation — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_agent_returns_error(websocket_url, auth_token, review_lifecycle):
    """Sending a message to a non-existent agent should return an error frame."""
    project_id = review_lifecycle["project_id"]
    async with websockets.connect(f"{websocket_url}?token={auth_token}") as ws:
        await ws.send(
            json.dumps(
                {
                    "action": "sendMessage",
                    "projectId": project_id,
                    "agent": "invalid_agent",
                    "message": "Test",
                    "sessionId": str(uuid4()),
                }
            )
        )
        data = json.loads(await ws.recv())

        assert data["type"] == "error"
        assert "invalid" in data["error"].lower() or "agent" in data["error"].lower()


@pytest.mark.asyncio
async def test_missing_fields_returns_error(websocket_url, auth_token, review_lifecycle):
    """Omitting required fields should return an error frame."""
    project_id = review_lifecycle["project_id"]
    async with websockets.connect(f"{websocket_url}?token={auth_token}") as ws:
        await ws.send(
            json.dumps(
                {
                    "action": "sendMessage",
                    "projectId": project_id,
                    # 'agent', 'message', 'sessionId' intentionally omitted
                }
            )
        )
        data = json.loads(await ws.recv())

        assert data["type"] == "error"


@pytest.mark.asyncio
async def test_nonexistent_project_returns_error(websocket_url, auth_token):
    """Referencing a project that doesn't exist should return an access denied error.

    The handler intentionally returns 'Access denied' rather than 'not found'
    to avoid leaking project existence to unauthorized users.
    """
    async with websockets.connect(f"{websocket_url}?token={auth_token}") as ws:
        await ws.send(
            json.dumps(
                {
                    "action": "sendMessage",
                    "projectId": "nonexistent-project-id",
                    "agent": "security",
                    "message": "Test",
                    "sessionId": str(uuid4()),
                }
            )
        )

        async for raw in ws:
            data = json.loads(raw)
            if data["type"] == "error":
                assert "access denied" in data["error"].lower()
                return

        pytest.fail("Expected an error frame for non-existent project")
