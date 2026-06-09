"""Unit test configuration.

These tests exercise pure logic only — no AWS calls, no network, no mocks of
AWS services. If a test needs AWS, it belongs in tests/live/.
"""
import sys
import os
import pytest

# Add project paths so imports work the same as in Lambda
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "agents"))


def pytest_collection_modifyitems(config, items):
    """Mark all tests in this directory as unit."""
    for item in items:
        if "/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)


def pytest_report_header(config):
    """Print a banner so the tester knows these are offline unit tests."""
    return [
        "",
        "═" * 60,
        "  🟢 UNIT TESTS — pure logic, no AWS calls",
        "═" * 60,
    ]


# ---------------------------------------------------------------------------
# Helpers for building API Gateway event dicts
# ---------------------------------------------------------------------------

@pytest.fixture
def make_apigw_event():
    """Factory fixture for building API Gateway v2 HTTP events.

    Usage:
        event = make_apigw_event(method="POST", path="/projects", body={"name": "Test"})
    """
    import json

    def _build(method="GET", path="/", body=None, query=None, path_params=None,
               claims=None):
        event = {
            "requestContext": {
                "http": {"method": method, "path": f"/v1{path}"},
                "stage": "v1",
                "authorizer": {
                    "jwt": {"claims": claims or {"sub": "test-user"}}
                },
            },
            "queryStringParameters": query,
        }
        if body is not None:
            event["body"] = json.dumps(body) if isinstance(body, dict) else body
        return event

    return _build
