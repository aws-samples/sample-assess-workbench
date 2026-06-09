"""Tests for the IndexDocument Lambda handler.

Tests mode dispatch, early returns when KB is not configured, and the
document identifier prefix-matching logic in _delete_prior_documents.
No AWS calls — boto3 clients are patched.
"""

import pytest
from unittest.mock import patch


class TestLambdaHandlerDispatch:

    @patch.dict("os.environ", {"DOCUMENT_KB_ID": "", "DOCUMENT_DS_ID": ""})
    def test_ingest_mode_skips_when_kb_not_configured(self):
        from api.workflow.index_document import lambda_handler

        result = lambda_handler({
            "mode": "ingest",
            "project_id": "proj-1",
            "review_id": "rev-1",
            "s3_bucket": "bucket",
            "document_s3_key": "key",
        }, None)

        assert result["indexing_status"] == "SKIPPED"
        assert result["document_identifier"] == ""

    @patch.dict("os.environ", {"DOCUMENT_KB_ID": "", "DOCUMENT_DS_ID": ""})
    def test_check_status_skips_when_kb_not_configured(self):
        from api.workflow.index_document import lambda_handler

        result = lambda_handler({
            "mode": "check_status",
            "project_id": "proj-1",
            "document_identifier": "proj-1-rev-1",
        }, None)

        assert result["indexing_status"] == "SKIPPED"

    def test_unknown_mode_raises(self):
        from api.workflow.index_document import lambda_handler

        with pytest.raises(ValueError, match="Unknown mode"):
            lambda_handler({"mode": "invalid"}, None)


class TestDeletePriorDocuments:
    """Tests the prefix-matching filter logic in _delete_prior_documents."""

    @patch.dict("os.environ", {
        "DOCUMENT_KB_ID": "kb-123",
        "DOCUMENT_DS_ID": "ds-456",
    })
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_deletes_matching_project_prefix(self, mock_client):
        mock_client.list_knowledge_base_documents.return_value = {
            "documentDetails": [
                {"identifier": {"custom": {"id": "proj-1-old-rev"}}},
                {"identifier": {"custom": {"id": "proj-1-rev-1"}}},
                {"identifier": {"custom": {"id": "proj-2-rev-1"}}},
            ]
        }
        mock_client.delete_knowledge_base_documents.return_value = {}

        from api.workflow.index_document import _delete_prior_documents
        _delete_prior_documents("proj-1", "proj-1-rev-1")

        # Should delete proj-1-old-rev but NOT proj-1-rev-1 (current)
        # and NOT proj-2-rev-1 (different project)
        delete_call = mock_client.delete_knowledge_base_documents.call_args
        identifiers = delete_call[1]["documentIdentifiers"]
        deleted_ids = [d["custom"]["id"] for d in identifiers]
        assert "proj-1-old-rev" in deleted_ids
        assert "proj-1-rev-1" not in deleted_ids
        assert "proj-2-rev-1" not in deleted_ids

    @patch.dict("os.environ", {
        "DOCUMENT_KB_ID": "kb-123",
        "DOCUMENT_DS_ID": "ds-456",
    })
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_no_delete_when_no_prior_documents(self, mock_client):
        mock_client.list_knowledge_base_documents.return_value = {
            "documentDetails": [
                {"identifier": {"custom": {"id": "proj-2-rev-1"}}},
            ]
        }

        from api.workflow.index_document import _delete_prior_documents
        _delete_prior_documents("proj-1", "proj-1-rev-1")

        mock_client.delete_knowledge_base_documents.assert_not_called()

    @patch.dict("os.environ", {
        "DOCUMENT_KB_ID": "kb-123",
        "DOCUMENT_DS_ID": "ds-456",
    })
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_handles_list_error_gracefully(self, mock_client):
        from botocore.exceptions import ClientError
        mock_client.list_knowledge_base_documents.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Denied"}},
            "ListKnowledgeBaseDocuments",
        )

        from api.workflow.index_document import _delete_prior_documents
        # Should not raise — failures are logged and swallowed
        _delete_prior_documents("proj-1", "proj-1-rev-1")
        mock_client.delete_knowledge_base_documents.assert_not_called()


class TestCheckStatusLogic:

    @patch("api.workflow.index_document.DOCUMENT_KB_ID", "kb-123")
    @patch("api.workflow.index_document.DOCUMENT_DS_ID", "ds-456")
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_indexed_status_returned(self, mock_client):
        mock_client.get_knowledge_base_documents.return_value = {
            "documentDetails": [
                {"status": {"type": "INDEXED"}}
            ]
        }

        from api.workflow.index_document import _handle_check_status
        result = _handle_check_status({
            "document_identifier": "proj-1-rev-1",
            "project_id": "proj-1",
        })
        assert result["indexing_status"] == "INDEXED"

    @patch("api.workflow.index_document.DOCUMENT_KB_ID", "kb-123")
    @patch("api.workflow.index_document.DOCUMENT_DS_ID", "ds-456")
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_failed_status_returned(self, mock_client):
        mock_client.get_knowledge_base_documents.return_value = {
            "documentDetails": [
                {"status": {"type": "FAILED", "reason": "Bad content"}}
            ]
        }

        from api.workflow.index_document import _handle_check_status
        result = _handle_check_status({
            "document_identifier": "proj-1-rev-1",
            "project_id": "proj-1",
        })
        assert result["indexing_status"] == "FAILED"
        assert "Bad content" in result.get("error", "")

    @patch("api.workflow.index_document.DOCUMENT_KB_ID", "kb-123")
    @patch("api.workflow.index_document.DOCUMENT_DS_ID", "ds-456")
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_empty_documents_returns_pending(self, mock_client):
        mock_client.get_knowledge_base_documents.return_value = {
            "documentDetails": []
        }

        from api.workflow.index_document import _handle_check_status
        result = _handle_check_status({
            "document_identifier": "proj-1-rev-1",
            "project_id": "proj-1",
        })
        assert result["indexing_status"] == "PENDING"

    @patch("api.workflow.index_document.DOCUMENT_KB_ID", "kb-123")
    @patch("api.workflow.index_document.DOCUMENT_DS_ID", "ds-456")
    @patch("api.workflow.index_document.bedrock_agent_client")
    def test_in_progress_returns_pending(self, mock_client):
        mock_client.get_knowledge_base_documents.return_value = {
            "documentDetails": [
                {"status": {"type": "IN_PROGRESS"}}
            ]
        }

        from api.workflow.index_document import _handle_check_status
        result = _handle_check_status({
            "document_identifier": "proj-1-rev-1",
            "project_id": "proj-1",
        })
        assert result["indexing_status"] == "PENDING"
