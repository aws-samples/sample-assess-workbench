# Testing Guide

Test against real infrastructure wherever possible. Only test offline when the
code is genuinely pure logic with no AWS interaction. Never mock AWS services —
if it needs AWS, test it against the real thing.

Tests are written against the contract (OpenAPI spec, function signatures), not
against current behavior. If a test fails on first run, that's a finding.

Coverage grows incrementally — when you pick up a backlog item, write tests for
the code you're touching.

## Categories

Two test categories, no grey area:

| Directory | Marker | What it tests | AWS needed? |
|-----------|--------|---------------|-------------|
| `tests/unit/` | `@pytest.mark.unit` | Pure logic — no network, no AWS, no mocks of AWS | No |
| `tests/live/` | `@pytest.mark.live` | Real deployed infrastructure via HTTP/WebSocket | Yes |

If a test needs AWS, it goes in `live/`. If it doesn't, it goes in `unit/`.
There is no middle ground with mocked AWS services.

## Running Tests

### From the command line (Taskfile)

```bash
# Unit tests only — fast, no AWS credentials needed
task test

# Live tests — full review lifecycle + API + WebSocket (~2-5 min)
task test:live

# All tests (unit + live)
task test:all

# Targeted: run only tests matching a keyword
task test:live -- -k "analytics"
task test:live -- -k "websocket"

# Targeted: run a single test file
uv run pytest tests/unit/test_plan_validation.py -v
uv run pytest tests/live/test_http_api.py -v -s
```

### From Kiro / VS Code Test Explorer

Click the beaker icon in the sidebar. All tests appear in the tree:
- `tests/unit/` tests run immediately — no setup needed.
- `tests/live/` tests auto-skip if endpoints or auth are not configured.

To run a single test, click the play button next to it.

## Live Test Configuration

Live tests need two things. All config goes in `.env` (already gitignored),
which is loaded by both the CLI (`task test:live`) and the IDE Test Explorer.

### 1. Deployed infrastructure (required)

Endpoints are auto-discovered from Terraform outputs, or set manually in `.env`:

```bash
API_ENDPOINT=https://<cloudfront-domain>/api
WEBSOCKET_URL=wss://<cloudfront-domain>/ws
```

Without endpoints, all live tests skip.
With just endpoints: `/health` and auth enforcement tests run.

### 2. Cognito credentials (for authenticated tests)

Add to `.env`:

```bash
TEST_USER_EMAIL=your-cognito-user@example.com
TEST_USER_PASSWORD=your-password
```

`COGNITO_CLIENT_ID` is auto-discovered from Terraform outputs.

With credentials: all tests run — HTTP API, review lifecycle, and WebSocket chat.

### Summary

| Configured | Tests that run |
|---|---|
| Endpoints only | `/health`, auth enforcement |
| + Cognito credentials | Everything (API, review lifecycle, WebSocket chat) |

## Review Lifecycle Fixture

The review lifecycle is driven by a session-scoped fixture in `conftest.py`,
not by individual test methods. The fixture:

1. Creates a project
2. Uploads a test document (`tests/fixtures/sample-design.txt`)
3. Triggers a review
4. Polls for the AI-generated plan
5. Approves with a 2-agent sequential plan (architecture → security)
6. Polls for completion
7. Verifies the response includes review data

All review flow tests and WebSocket chat tests share this single project.
The fixture deletes the project on teardown.

If any step fails, the fixture raises with a specific diagnostic message
(e.g. "Plan not ready after 60 polls" or "HTTP 403 on approve"). Tests
that depend on the fixture skip with the failure reason rather than
cascading into confusing assertion errors.

## Test Structure

```
tests/
├── conftest.py                    # Root config: markers, shared fixtures
├── unit/                          # 🟢 Pure logic tests
│   ├── conftest.py                #   Path setup, API Gateway event factory
│   ├── test_parsers.py            #   Request/response parsing
│   ├── test_responses.py          #   HTTP response builders
│   ├── test_plan_validation.py    #   Review plan validation & judge config
│   ├── test_risk_matrix.py        #   ISO 31000 risk matrix
│   ├── test_router.py             #   URL pattern matching
│   └── test_workflow_logic.py     #   Workflow Lambda pure functions
├── live/                          # 🔴 Real AWS infrastructure tests
│   ├── conftest.py                #   Endpoint discovery, auth, review lifecycle fixture
│   ├── test_http_api.py           #   HTTP API contract (health, projects, analytics)
│   ├── test_review_flow.py        #   Review findings, events, document, report, feedback
│   └── test_websocket_chat.py     #   WebSocket chat with deployed agents
└── test_websocket_integration.sh  # Shell wrapper for WebSocket tests
```

## Console Output

Unit tests print:
```
════════════════════════════════════════════════════════════
  🟢 UNIT TESTS — pure logic, no AWS calls
════════════════════════════════════════════════════════════
```

Live tests print:
```
════════════════════════════════════════════════════════════
  🔴 LIVE TESTS — hitting real AWS infrastructure
  HTTP API:   https://<cloudfront-domain>/api
  WebSocket:  wss://<cloudfront-domain>/ws
  Auth:       configured
════════════════════════════════════════════════════════════
```
