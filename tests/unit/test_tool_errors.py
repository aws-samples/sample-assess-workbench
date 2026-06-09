"""Tests for the shared handle_tool_errors decorator."""

import pytest
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from shared.tools.errors import handle_tool_errors


def _make_client_error(code="ResourceNotFoundException", message="Not found"):
    """Build a botocore ClientError."""
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "TestOperation",
    )


class TestHandleToolErrors:

    def test_returns_normal_result_on_success(self):
        @handle_tool_errors
        def good_tool():
            return "result"

        assert good_tool() == "result"

    def test_catches_client_error(self):
        @handle_tool_errors
        def failing_tool():
            raise _make_client_error()

        result = failing_tool()
        assert result.startswith("[ERROR]")
        assert "failing_tool" in result

    def test_catches_botocore_error(self):
        @handle_tool_errors
        def failing_tool():
            raise BotoCoreError()

        result = failing_tool()
        assert result.startswith("[ERROR]")

    def test_catches_endpoint_connection_error(self):
        @handle_tool_errors
        def failing_tool():
            raise EndpointConnectionError(endpoint_url="https://example.com")

        result = failing_tool()
        assert result.startswith("[ERROR]")

    def test_propagates_type_error(self):
        @handle_tool_errors
        def buggy_tool():
            raise TypeError("bad argument")

        with pytest.raises(TypeError, match="bad argument"):
            buggy_tool()

    def test_propagates_key_error(self):
        @handle_tool_errors
        def buggy_tool():
            raise KeyError("missing_key")

        with pytest.raises(KeyError):
            buggy_tool()

    def test_propagates_value_error(self):
        @handle_tool_errors
        def buggy_tool():
            raise ValueError("invalid")

        with pytest.raises(ValueError, match="invalid"):
            buggy_tool()

    def test_preserves_function_name(self):
        @handle_tool_errors
        def my_named_tool():
            return "ok"

        assert my_named_tool.__name__ == "my_named_tool"

    def test_error_message_includes_exception_detail(self):
        @handle_tool_errors
        def failing_tool():
            raise _make_client_error(code="ThrottlingException", message="Rate exceeded")

        result = failing_tool()
        assert "ThrottlingException" in result or "Rate exceeded" in result
