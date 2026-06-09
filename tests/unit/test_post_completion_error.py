"""Unit tests for error message extraction — shared across error handlers.

Tests the extract_error_message function in api/core/errors.py, which parses
Step Functions Catch error payloads into human-readable messages.
"""

from core.errors import extract_error_message, DEFAULT_MAX_LENGTH


class TestExtractErrorMessage:
    """Tests for extract_error_message — Step Functions error payload parsing."""

    def test_string_error(self):
        assert extract_error_message("something broke") == "something broke"

    def test_string_truncated_to_max_length(self):
        long_msg = "x" * 2000
        result = extract_error_message(long_msg)
        assert len(result) == DEFAULT_MAX_LENGTH

    def test_dict_with_error_and_cause(self):
        raw = {"Error": "States.TaskFailed", "Cause": "Lambda timed out"}
        assert extract_error_message(raw) == "States.TaskFailed: Lambda timed out"

    def test_dict_with_error_only(self):
        raw = {"Error": "States.TaskFailed"}
        assert extract_error_message(raw) == "States.TaskFailed"

    def test_dict_with_cause_only(self):
        raw = {"Cause": "DynamoDB throttled"}
        assert extract_error_message(raw) == "DynamoDB throttled"

    def test_dict_with_neither_falls_back_to_json(self):
        raw = {"foo": "bar"}
        result = extract_error_message(raw)
        assert "foo" in result
        assert "bar" in result

    def test_dict_cause_truncated(self):
        raw = {"Error": "E", "Cause": "C" * 2000}
        result = extract_error_message(raw)
        assert len(result) == DEFAULT_MAX_LENGTH

    def test_empty_dict(self):
        result = extract_error_message({})
        assert result == "{}"

    def test_none_converted_to_string(self):
        result = extract_error_message(None)
        assert result == "None"

    def test_integer_converted_to_string(self):
        result = extract_error_message(42)
        assert result == "42"

    def test_empty_string(self):
        assert extract_error_message("") == ""

    def test_custom_max_length(self):
        result = extract_error_message("x" * 500, max_length=100)
        assert len(result) == 100
