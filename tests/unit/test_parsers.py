"""Unit tests for request/response parsers.

Source: api/rest_api/utils/parsers.py
Contract: parse API Gateway v2 events, convert DynamoDB Decimals, parse AgentCore responses.
"""

import json
from decimal import Decimal

import pytest
from rest_api.utils.parsers import parse_body, decimal_to_number, deserialize_review


# ═══════════════════════════════════════════════════════════════════════════
# parse_body
# ═══════════════════════════════════════════════════════════════════════════


class TestParseBody:
    """API Gateway v2 sends the body as a JSON string. parse_body should
    handle both string and pre-parsed dict forms, plus edge cases."""

    def test_json_string_body(self):
        event = {"body": json.dumps({"name": "Test Project"})}
        assert parse_body(event) == {"name": "Test Project"}

    def test_dict_body_passed_through(self):
        event = {"body": {"name": "Already Parsed"}}
        assert parse_body(event) == {"name": "Already Parsed"}

    def test_missing_body_returns_full_event(self):
        event = {"queryStringParameters": {"status": "pending"}}
        result = parse_body(event)
        assert result == event

    def test_empty_string_body_raises(self):
        """An empty string is not valid JSON — should raise."""
        with pytest.raises(json.JSONDecodeError):
            parse_body({"body": ""})

    def test_none_body_returns_full_event(self):
        event = {"body": None, "path": "/projects"}
        result = parse_body(event)
        assert result == event


# ═══════════════════════════════════════════════════════════════════════════
# decimal_to_number
# ═══════════════════════════════════════════════════════════════════════════


class TestDecimalToNumber:
    """DynamoDB returns numbers as Decimal. These must become int or float
    before JSON serialization."""

    def test_whole_decimal_becomes_int(self):
        assert decimal_to_number(Decimal("42")) == 42
        assert isinstance(decimal_to_number(Decimal("42")), int)

    def test_fractional_decimal_becomes_float(self):
        assert decimal_to_number(Decimal("3.14")) == pytest.approx(3.14)
        assert isinstance(decimal_to_number(Decimal("3.14")), float)

    def test_zero(self):
        assert decimal_to_number(Decimal("0")) == 0
        assert isinstance(decimal_to_number(Decimal("0")), int)

    def test_nested_dict(self):
        data = {"count": Decimal("5"), "score": Decimal("0.85")}
        result = decimal_to_number(data)
        assert result == {"count": 5, "score": pytest.approx(0.85)}

    def test_nested_list(self):
        data = [Decimal("1"), Decimal("2.5"), "text"]
        result = decimal_to_number(data)
        assert result == [1, pytest.approx(2.5), "text"]

    def test_deeply_nested(self):
        data = {"items": [{"value": Decimal("99")}]}
        result = decimal_to_number(data)
        assert result == {"items": [{"value": 99}]}

    def test_non_decimal_passthrough(self):
        assert decimal_to_number("hello") == "hello"
        assert decimal_to_number(42) == 42
        assert decimal_to_number(None) is None


# ═══════════════════════════════════════════════════════════════════════════
# deserialize_review
# ═══════════════════════════════════════════════════════════════════════════


class TestDeserializeReview:
    """deserialize_review normalizes REVIEW# items from DynamoDB.

    Findings are stored in S3 — the caller hydrates them before calling
    this function. deserialize_review only handles the no-S3-reference
    case (defaulting findings to {}) and validates that S3-referenced
    items have been properly hydrated."""

    def test_no_s3_reference_defaults_findings_to_empty_dict(self):
        item = {"review_id": "rev_1", "status": "completed"}
        result = deserialize_review(item)
        assert result["findings"] == {}

    def test_no_s3_reference_preserves_existing_findings(self):
        findings = {"reviews": {"security": {"findings": []}}}
        item = {"review_id": "rev_2", "findings": findings}
        result = deserialize_review(item)
        assert result["findings"] is findings

    def test_s3_reference_with_hydrated_findings_passes_through(self):
        findings = {"reviews": {"arch": {}}}
        item = {
            "review_id": "rev_3",
            "findings_s3_bucket": "my-bucket",
            "findings_s3_key": "findings.json",
            "findings": findings,
        }
        result = deserialize_review(item)
        assert result["findings"] is findings

    def test_s3_reference_without_hydrated_findings_raises(self):
        item = {
            "review_id": "rev_4",
            "findings_s3_bucket": "my-bucket",
            "findings_s3_key": "findings.json",
        }
        with pytest.raises(ValueError, match="not hydrated"):
            deserialize_review(item)

    def test_none_findings_unchanged(self):
        item = {"review_id": "rev_5", "findings": None}
        result = deserialize_review(item)
        assert result["findings"] is None
