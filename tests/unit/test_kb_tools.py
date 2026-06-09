"""Tests for Bedrock Knowledge Base agent tools.

Tests the pure logic in kb_tools.py: result formatting, metadata filter
construction, input validation, and error paths. No AWS calls.

Note: The tool functions (search_document, lookup_standard) are decorated
with @tool from strands, which isn't available in the unit test environment.
We test the pure helper functions directly and test tool logic via the
module's internal functions by patching the strands import.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

# Patch strands before importing kb_tools — strands is an AgentCore
# dependency not available in the unit test environment.
_mock_strands = MagicMock()
# Make @tool(context=True) a passthrough decorator
_mock_strands.tool = lambda **kwargs: lambda fn: fn
sys.modules.setdefault("strands", _mock_strands)
sys.modules.setdefault("strands.types", MagicMock())
sys.modules.setdefault("strands.types.tools", MagicMock())

# Now we can import — the @tool decorator is a no-op
from shared.tools.kb_tools import (
    _format_kb_results,
    search_document,
    lookup_standard,
)


# ── _format_kb_results (pure function) ───────────────────────────


class TestFormatKbResults:

    def test_empty_results(self):
        assert _format_kb_results([]) == ""

    def test_single_result(self):
        results = [{"content": {"text": "Some chunk text"}}]
        assert _format_kb_results(results) == "Some chunk text"

    def test_multiple_results_separated_by_divider(self):
        results = [
            {"content": {"text": "First chunk"}},
            {"content": {"text": "Second chunk"}},
        ]
        formatted = _format_kb_results(results)
        assert "First chunk" in formatted
        assert "Second chunk" in formatted
        assert "---" in formatted

    def test_strips_whitespace_from_chunks(self):
        results = [{"content": {"text": "  padded text  \n"}}]
        assert _format_kb_results(results) == "padded text"

    def test_skips_empty_text_chunks(self):
        results = [
            {"content": {"text": "real content"}},
            {"content": {"text": ""}},
            {"content": {"text": "   "}},
        ]
        formatted = _format_kb_results(results)
        assert "real content" in formatted
        # Only one real chunk — no dividers
        assert formatted.count("---") == 0

    def test_missing_content_key(self):
        results = [{"score": 0.9}]
        assert _format_kb_results(results) == ""

    def test_missing_text_key(self):
        results = [{"content": {}}]
        assert _format_kb_results(results) == ""


# ── search_document tool logic ───────────────────────────────────


class TestSearchDocumentLogic:

    def _make_tool_context(self, project_id="proj-1", document_kb_id="kb-123"):
        ctx = MagicMock()
        ctx.invocation_state = {
            "project_id": project_id,
            "document_kb_id": document_kb_id,
        }
        return ctx

    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_builds_project_id_metadata_filter(self, mock_retrieve):
        mock_retrieve.return_value = [{"content": {"text": "chunk"}}]
        ctx = self._make_tool_context()

        search_document(query="authentication", tool_context=ctx)

        mock_retrieve.assert_called_once()
        _, query, metadata_filter = mock_retrieve.call_args[0]
        assert query == "authentication"
        assert metadata_filter["equals"]["key"] == "project_id"
        assert metadata_filter["equals"]["value"] == "proj-1"

    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_section_hint_appended_to_query(self, mock_retrieve):
        mock_retrieve.return_value = []
        ctx = self._make_tool_context()

        search_document(query="auth", section_hint="Chapter 3", tool_context=ctx)

        search_query = mock_retrieve.call_args[0][1]
        assert "auth" in search_query
        assert "Chapter 3" in search_query

    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_no_results_returns_not_found_message(self, mock_retrieve):
        mock_retrieve.return_value = []
        ctx = self._make_tool_context()

        result = search_document(query="xyz", tool_context=ctx)
        assert "No matching sections" in result

    def test_missing_document_kb_id_raises(self):
        ctx = self._make_tool_context(document_kb_id="")

        with pytest.raises(ValueError, match="document_kb_id"):
            search_document(query="test", tool_context=ctx)

    def test_missing_project_id_raises(self):
        ctx = self._make_tool_context(project_id="")

        with pytest.raises(ValueError, match="project_id"):
            search_document(query="test", tool_context=ctx)


# ── lookup_standard tool logic ───────────────────────────────────


class TestLookupStandardLogic:

    def _make_tool_context(self, standards_kb_id="kb-std-1"):
        ctx = MagicMock()
        ctx.invocation_state = {
            "standards_kb_id": standards_kb_id,
        }
        return ctx

    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_single_standard_filter(self, mock_retrieve):
        mock_retrieve.return_value = [{"content": {"text": "OWASP A01"}}]
        ctx = self._make_tool_context()

        lookup_standard(
            standard="owasp-top-10", query="broken access control",
            tool_context=ctx,
        )

        _, _, metadata_filter = mock_retrieve.call_args[0]
        assert metadata_filter["equals"]["key"] == "standard_id"
        assert metadata_filter["equals"]["value"] == "owasp-top-10"

    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_standard_plus_section_uses_and_all(self, mock_retrieve):
        mock_retrieve.return_value = [{"content": {"text": "Art.32 text"}}]
        ctx = self._make_tool_context()

        lookup_standard(standard="gdpr", section="Art.32", tool_context=ctx)

        _, _, metadata_filter = mock_retrieve.call_args[0]
        assert "andAll" in metadata_filter
        filters = metadata_filter["andAll"]
        assert len(filters) == 2
        keys = {f["equals"]["key"] for f in filters}
        assert keys == {"standard_id", "section"}

    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_section_used_as_query_when_no_free_text(self, mock_retrieve):
        mock_retrieve.return_value = [{"content": {"text": "result"}}]
        ctx = self._make_tool_context()

        lookup_standard(standard="gdpr", section="Art.32", tool_context=ctx)

        search_query = mock_retrieve.call_args[0][1]
        assert "Art.32" in search_query

    def test_no_section_and_no_query_returns_guidance(self):
        ctx = self._make_tool_context()

        result = lookup_standard(standard="owasp-top-10", tool_context=ctx)
        assert "section" in result.lower() or "query" in result.lower()

    @patch("shared.tools.kb_tools._get_available_standards")
    @patch("shared.tools.kb_tools._retrieve_from_kb")
    def test_not_found_includes_available_standards(
        self, mock_retrieve, mock_available,
    ):
        mock_retrieve.return_value = []
        mock_available.return_value = ["owasp-top-10", "gdpr"]
        ctx = self._make_tool_context()

        result = lookup_standard(
            standard="nist-800-53", query="access control",
            tool_context=ctx,
        )
        assert "not found" in result.lower()
        assert "owasp-top-10" in result
        assert "unverified" in result.lower()

    def test_missing_standards_kb_id_raises(self):
        ctx = self._make_tool_context(standards_kb_id="")

        with pytest.raises(ValueError, match="standards_kb_id"):
            lookup_standard(
                standard="owasp-top-10", query="test", tool_context=ctx,
            )
