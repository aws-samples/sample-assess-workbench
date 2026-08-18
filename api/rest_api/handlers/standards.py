"""Standards corpus request handlers — protected by Cognito admin group."""

import json
import logging
from typing import Any, Dict

from botocore.exceptions import ClientError

from ..services.standards_service import StandardsService
from ..utils import success_response, error_response, get_user_role, UserRole, can_read_admin_views

logger = logging.getLogger(__name__)


def _is_admin(event: Dict[str, Any]) -> bool:
    """Check if the caller belongs to the admin Cognito group."""
    try:
        return get_user_role(event) == UserRole.ADMIN
    except PermissionError:
        return False


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the JSON request body from an API Gateway v2 event.

    Args:
        event: API Gateway v2 event dict.

    Returns:
        Parsed body dict.

    Raises:
        ValueError: If the body is missing or not valid JSON.
    """
    raw = event.get("body")
    if not raw:
        raise ValueError("Request body is required")
    return json.loads(raw)


class StandardsHandlers:
    """Handles standards corpus HTTP requests."""

    def __init__(self, standards_service: StandardsService):
        self.standards_service = standards_service

    def list_standards(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /admin/standards — list all standards in the corpus.

        Args:
            event: API Gateway v2 event dict.
            context: Lambda context.

        Returns:
            JSON response with standards list, count, and bucket name.
        """
        if not can_read_admin_views(event):
            return error_response(403, "Admin access required")
        try:
            result = self.standards_service.list_standards()
            return success_response(result)
        except Exception as e:
            logger.error("Error listing standards: %s", e, exc_info=True)
            return error_response(500, "Failed to list standards")

    def upload_standard(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle POST /admin/standards — upload a new standard.

        Validates inputs, writes the metadata sidecar to S3, and returns
        a pre-signed URL for the caller to upload the ``.md`` file.

        Args:
            event: API Gateway v2 event dict.
            context: Lambda context.

        Returns:
            JSON response with ``upload_url``, ``s3_key``, and ``metadata_written``.
        """
        if not _is_admin(event):
            return error_response(403, "Admin access required")
        try:
            body = _parse_body(event)
        except (ValueError, json.JSONDecodeError) as e:
            return error_response(400, f"Invalid request body: {e}")

        standard_id = body.get("standard_id", "").strip()
        source_type = body.get("source_type", "").strip()
        filename = body.get("filename", "").strip()
        content_type = body.get("content_type", "text/markdown").strip()

        if not standard_id or not source_type or not filename:
            return error_response(400, "standard_id, source_type, and filename are required")

        try:
            result = self.standards_service.upload_standard(
                standard_id=standard_id,
                source_type=source_type,
                filename=filename,
                jurisdiction=body.get("jurisdiction", "").strip(),
                industry=body.get("industry", "").strip(),
                content_type=content_type,
            )
            return success_response(result, status_code=201)
        except ValueError as e:
            return error_response(400, str(e))
        except ClientError as e:
            logger.error("S3 error uploading standard '%s': %s", standard_id, e, exc_info=True)
            return error_response(500, "Failed to upload standard")

    def delete_standard(
        self, standard_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle DELETE /admin/standards/{standard_id} — delete a standard.

        Args:
            standard_id: Path parameter — the standard to delete.
            event: API Gateway v2 event dict.
            context: Lambda context.

        Returns:
            JSON response with ``standard_id`` and ``objects_deleted``.
        """
        if not _is_admin(event):
            return error_response(403, "Admin access required")
        try:
            result = self.standards_service.delete_standard(standard_id)
            return success_response(result)
        except ValueError as e:
            return error_response(400, str(e))
        except ClientError as e:
            logger.error("S3 error deleting standard '%s': %s", standard_id, e, exc_info=True)
            return error_response(500, "Failed to delete standard")

    def update_metadata(
        self, standard_id: str, event: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Handle PUT /admin/standards/{standard_id}/metadata — edit sidecar.

        Rewrites the metadata sidecar without touching the ``.md`` file.

        Args:
            standard_id: Path parameter — the standard to update.
            event: API Gateway v2 event dict.
            context: Lambda context.

        Returns:
            JSON response with ``standard_id`` and ``metadata_written``.
        """
        if not _is_admin(event):
            return error_response(403, "Admin access required")
        try:
            body = _parse_body(event)
        except (ValueError, json.JSONDecodeError) as e:
            return error_response(400, f"Invalid request body: {e}")

        source_type = body.get("source_type", "").strip()
        if not source_type:
            return error_response(400, "source_type is required")

        try:
            result = self.standards_service.update_metadata(
                standard_id=standard_id,
                source_type=source_type,
                jurisdiction=body.get("jurisdiction", "").strip(),
                industry=body.get("industry", "").strip(),
            )
            return success_response(result)
        except ValueError as e:
            return error_response(400, str(e))
        except ClientError as e:
            logger.error("S3 error updating metadata for '%s': %s", standard_id, e, exc_info=True)
            return error_response(500, "Failed to update metadata")

    def start_sync(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle POST /admin/standards/sync — trigger KB ingestion job.

        Args:
            event: API Gateway v2 event dict.
            context: Lambda context.

        Returns:
            JSON response with ``ingestion_job_id`` and ``status``.
        """
        if not _is_admin(event):
            return error_response(403, "Admin access required")
        try:
            result = self.standards_service.start_sync()
            return success_response(result)
        except RuntimeError as e:
            return error_response(503, str(e))
        except ClientError as e:
            logger.error("Bedrock error starting sync: %s", e, exc_info=True)
            return error_response(500, "Failed to start KB sync")

    def get_sync_status(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """Handle GET /admin/standards/sync-status — poll ingestion job status.

        Args:
            event: API Gateway v2 event dict.
            context: Lambda context.

        Returns:
            JSON response with latest ingestion job status and statistics.
        """
        if not can_read_admin_views(event):
            return error_response(403, "Admin access required")
        try:
            result = self.standards_service.get_sync_status()
            return success_response(result)
        except RuntimeError as e:
            return error_response(503, str(e))
        except ClientError as e:
            logger.error("Bedrock error getting sync status: %s", e, exc_info=True)
            return error_response(500, "Failed to get sync status")
