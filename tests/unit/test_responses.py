"""Unit tests for HTTP response builders.

Source: api/rest_api/utils/responses.py
Contract: build API Gateway v2 response dicts with correct status codes,
          security headers, and JSON bodies.
"""

import json
from decimal import Decimal

from rest_api.utils.responses import success_response, error_response


# ═══════════════════════════════════════════════════════════════════════════
# success_response
# ═══════════════════════════════════════════════════════════════════════════


class TestSuccessResponse:
    def test_default_status_code_is_200(self):
        resp = success_response({"ok": True})
        assert resp["statusCode"] == 200

    def test_custom_status_code(self):
        resp = success_response({"id": "abc"}, status_code=201)
        assert resp["statusCode"] == 201

    def test_body_is_json_string(self):
        resp = success_response({"count": 3})
        body = json.loads(resp["body"])
        assert body == {"count": 3}

    def test_decimals_are_serialized(self):
        resp = success_response({"score": Decimal("0.95"), "count": Decimal("7")})
        body = json.loads(resp["body"])
        assert body["score"] == 0.95
        assert body["count"] == 7

    def test_security_headers_present(self):
        resp = success_response({})
        headers = resp["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "max-age" in headers["Strict-Transport-Security"]
        assert headers["Cache-Control"] == "no-store"


# ═══════════════════════════════════════════════════════════════════════════
# error_response
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorResponse:
    def test_error_message_in_body(self):
        resp = error_response(400, "Missing required field: name")
        body = json.loads(resp["body"])
        assert body["error"] == "Missing required field: name"

    def test_details_included_for_4xx(self):
        resp = error_response(400, "Bad request", details="name is required")
        body = json.loads(resp["body"])
        assert body["details"] == "name is required"

    def test_details_excluded_for_5xx(self):
        """5xx responses should never leak internal details."""
        resp = error_response(500, "Internal server error", details="traceback...")
        body = json.loads(resp["body"])
        assert "details" not in body

    def test_status_code_passed_through(self):
        assert error_response(404, "Not found")["statusCode"] == 404
        assert error_response(409, "Conflict")["statusCode"] == 409

    def test_security_headers_on_errors(self):
        resp = error_response(500, "Error")
        assert resp["headers"]["X-Frame-Options"] == "DENY"
