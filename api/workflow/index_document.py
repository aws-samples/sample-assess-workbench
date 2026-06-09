"""Index Document Lambda — pushes document content to Bedrock Knowledge Base.

Two modes of operation, driven by the ``mode`` field in the event:

1. **ingest** (default): Reads ``document.json`` from S3, deletes any
   prior documents for this project, and pushes content to the Document
   Index KB via ``IngestKnowledgeBaseDocuments``. Returns the ingestion
   job ID for the Step Functions wait/retry pattern.

2. **check_status**: Polls ``GetKnowledgeBaseDocuments`` to check whether
   the ingested document is indexed and available for retrieval.

The Step Functions ASL orchestrates these two modes with a Wait state
between them, avoiding idle Lambda compute during indexing.
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from core.progress import send_progress, set_user_sub, set_review_context
from core.s3 import read_json

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
# This Lambda is called in two modes with different required fields.
# The union is declared here; mode-specific validation is in the handler.
EXPECTED_EVENT = {
    'required': ['project_id', 'review_id', 'mode'],
    'optional': ['s3_bucket', 'document_s3_key', 'document_identifier',
                 'connection_id', 'user_sub', 'websocket_endpoint'],
}

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DOCUMENT_KB_ID = os.environ.get("DOCUMENT_KB_ID", "")
DOCUMENT_DS_ID = os.environ.get("DOCUMENT_DS_ID", "")
WEBSOCKET_API_ENDPOINT = os.environ.get("WEBSOCKET_API_ENDPOINT", "")

bedrock_agent_client = boto3.client("bedrock-agent")


def lambda_handler(event: dict, context) -> dict:
    """Route to ingest or check_status based on event mode."""
    mode = event.get("mode", "ingest")

    if mode == "ingest":
        return _handle_ingest(event)
    elif mode == "check_status":
        return _handle_check_status(event)
    else:
        raise ValueError(f"Unknown mode: {mode}")


def _handle_ingest(event: dict) -> dict:
    """Read document from S3 and push to Bedrock KB for indexing.

    Args:
        event: Step Functions payload with project_id, review_id,
            s3_bucket, document_s3_key, and WebSocket fields.

    Returns:
        Dict with ``document_identifier`` for status checking and
        ``indexing_status`` set to ``STARTING``.
    """
    project_id = event["project_id"]
    review_id = event["review_id"]
    s3_bucket = event["s3_bucket"]
    document_s3_key = event["document_s3_key"]
    connection_id = event.get("connection_id", "")
    websocket_endpoint = event.get("websocket_endpoint", "") or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get("user_sub", ""))
    set_review_context(project_id, review_id)

    if not DOCUMENT_KB_ID or not DOCUMENT_DS_ID:
        logger.info(
            "Document KB not configured (DOCUMENT_KB_ID=%s, DOCUMENT_DS_ID=%s) "
            "— skipping indexing",
            DOCUMENT_KB_ID,
            DOCUMENT_DS_ID,
        )
        return {
            "indexing_status": "SKIPPED",
            "document_identifier": "",
        }

    send_progress(connection_id, websocket_endpoint, "document_indexing_started", {
        "project_id": project_id,
    })

    # Read document content from S3 (written by LoadDocument)
    doc_data = read_json(s3_bucket, document_s3_key)
    document_content = doc_data["document_content"]

    document_identifier = f"{project_id}-{review_id}"

    # Delete prior documents for this project before ingesting new ones.
    # This prevents stale chunks from prior document versions appearing
    # in search results on re-review.
    _delete_prior_documents(project_id, document_identifier)

    # Ingest document content inline (no S3 staging needed).
    # Bedrock KB handles chunking, embedding, and indexing.
    logger.info(
        "Ingesting document for project %s (identifier: %s, content length: %d)",
        project_id,
        document_identifier,
        len(document_content),
    )

    ingest_response = bedrock_agent_client.ingest_knowledge_base_documents(
        knowledgeBaseId=DOCUMENT_KB_ID,
        dataSourceId=DOCUMENT_DS_ID,
        documents=[
            {
                "content": {
                    "custom": {
                        "customDocumentIdentifier": {
                            "id": document_identifier,
                        },
                        "sourceType": "IN_LINE",
                        "inlineContent": {
                            "type": "TEXT",
                            "textContent": {
                                "data": document_content,
                            },
                        },
                    },
                },
                "metadata": {
                    "inlineAttributes": [
                        {
                            "key": "project_id",
                            "value": {"stringValue": project_id},
                        },
                        {
                            "key": "review_id",
                            "value": {"stringValue": review_id},
                        },
                    ],
                    "type": "IN_LINE_ATTRIBUTE",
                },
            }
        ],
    )

    # Log the response for debugging — the API returns per-document status.
    documents = ingest_response.get("documents", [])
    if documents:
        status = documents[0].get("status", {})
        logger.info(
            "Ingest response for %s: %s",
            document_identifier,
            status,
        )

    return {
        "indexing_status": "STARTED",
        "document_identifier": document_identifier,
    }


def _handle_check_status(event: dict) -> dict:
    """Check whether the ingested document is indexed and queryable.

    Args:
        event: Step Functions payload with document_identifier and
            indexing metadata.

    Returns:
        Dict with updated ``indexing_status``: ``INDEXED``, ``FAILED``,
        or ``PENDING`` (triggers another wait/retry cycle in the ASL).
    """
    document_identifier = event["document_identifier"]
    project_id = event["project_id"]
    connection_id = event.get("connection_id", "")
    websocket_endpoint = event.get("websocket_endpoint", "") or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get("user_sub", ""))
    set_review_context(project_id, event.get("review_id", ""))

    if not DOCUMENT_KB_ID or not DOCUMENT_DS_ID:
        return {"indexing_status": "SKIPPED", "document_identifier": ""}

    try:
        response = bedrock_agent_client.get_knowledge_base_documents(
            knowledgeBaseId=DOCUMENT_KB_ID,
            dataSourceId=DOCUMENT_DS_ID,
            documentIdentifiers=[
                {
                    "custom": {
                        "id": document_identifier,
                    },
                    "dataSourceType": "CUSTOM",
                }
            ],
        )
    except ClientError as e:
        logger.error(
            "Failed to check document status for %s: %s",
            document_identifier,
            e,
        )
        return {
            "indexing_status": "FAILED",
            "document_identifier": document_identifier,
            "error": str(e),
        }

    documents = response.get("documentDetails", [])
    if not documents:
        # Document not found yet — still processing
        logger.info("Document %s not found yet — still indexing", document_identifier)
        return {
            "indexing_status": "PENDING",
            "document_identifier": document_identifier,
        }

    doc_status = documents[0].get("status", {}).get("type", "UNKNOWN")
    logger.info("Document %s status: %s", document_identifier, doc_status)

    if doc_status == "INDEXED":
        send_progress(connection_id, websocket_endpoint, "document_indexing_completed", {
            "project_id": project_id,
        })
        return {
            "indexing_status": "INDEXED",
            "document_identifier": document_identifier,
        }
    elif doc_status in ("FAILED", "PARTIALLY_INDEXED"):
        status_reason = documents[0].get("status", {}).get("reason", "Unknown")
        logger.error(
            "Document indexing failed for %s: %s (%s)",
            document_identifier,
            doc_status,
            status_reason,
        )
        send_progress(connection_id, websocket_endpoint, "document_indexing_failed", {
            "project_id": project_id,
            "reason": status_reason,
        })
        return {
            "indexing_status": "FAILED",
            "document_identifier": document_identifier,
            "error": f"{doc_status}: {status_reason}",
        }
    else:
        # PENDING, STARTING, IN_PROGRESS, METADATA_PARTIALLY_INDEXED, etc.
        return {
            "indexing_status": "PENDING",
            "document_identifier": document_identifier,
        }


def _delete_prior_documents(project_id: str, current_identifier: str) -> None:
    """Delete previously indexed documents for this project.

    Queries the KB for documents with matching project_id metadata,
    then deletes any that don't match the current review's identifier.
    Failures are logged but don't block ingestion — stale chunks are
    a quality issue, not a correctness issue.

    Args:
        project_id: Project identifier for metadata filtering.
        current_identifier: The current review's document identifier
            (not deleted).
    """
    try:
        # List documents in the data source to find prior project documents.
        # The list API doesn't support metadata filtering, so we list all
        # and filter client-side. For the expected document volume (one per
        # project per review), this is fine.
        response = bedrock_agent_client.list_knowledge_base_documents(
            knowledgeBaseId=DOCUMENT_KB_ID,
            dataSourceId=DOCUMENT_DS_ID,
            maxResults=100,
        )

        to_delete = []
        for doc in response.get("documentDetails", []):
            identifier = doc.get("identifier", {}).get("custom", {}).get("id", "")
            # Convention: identifiers are "{project_id}-{review_id}".
            # Match on project_id prefix but skip the current review.
            if identifier.startswith(f"{project_id}-") and identifier != current_identifier:
                to_delete.append({
                    "custom": {"id": identifier},
                    "dataSourceType": "CUSTOM",
                })

        if to_delete:
            logger.info(
                "Deleting %d prior document(s) for project %s",
                len(to_delete),
                project_id,
            )
            bedrock_agent_client.delete_knowledge_base_documents(
                knowledgeBaseId=DOCUMENT_KB_ID,
                dataSourceId=DOCUMENT_DS_ID,
                documentIdentifiers=to_delete,
            )
    except ClientError:
        logger.warning(
            "Failed to delete prior documents for project %s — continuing",
            project_id,
            exc_info=True,
        )
