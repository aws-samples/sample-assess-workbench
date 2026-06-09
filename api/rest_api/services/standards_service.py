"""Standards corpus service — visibility and management of the standards S3 bucket."""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import boto3

from ..data_access import S3DataAccess

logger = logging.getLogger(__name__)

# Valid standard_id: kebab-case, alphanumeric + hyphens, 1-100 chars
_STANDARD_ID_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

# Allowed source_type values
VALID_SOURCE_TYPES = frozenset({
    'prudential_standard',
    'prudential_guidance',
    'regulatory_commentary',
    'industry_framework',
    'legislation',
})

# Allowed jurisdiction values
VALID_JURISDICTIONS = frozenset({
    'AU',
    'EU',
    'US',
    'UK',
    'international',
})

# Allowed industry values
VALID_INDUSTRIES = frozenset({
    'financial_services',
    'general',
    'automotive',
})


class StandardsService:
    """Lists, uploads, deletes, and syncs standards documents in S3.

    Each standard lives in a directory named after its ``standard_id``
    (e.g. ``cps-230/cps-230.pdf``) with a JSON metadata sidecar next to
    the content file (``cps-230/cps-230.pdf.metadata.json``).

    Content files can be any format supported by Bedrock KB (md, pdf, txt,
    html, doc, docx, csv). The service discovers the actual content file
    by listing the prefix rather than assuming a specific extension.

    Args:
        s3: S3DataAccess instance pointed at the standards bucket.
        kb_id: Bedrock Knowledge Base ID for ingestion operations. Optional —
            sync endpoints are unavailable when not set.
        ds_id: Bedrock KB data source ID. Required alongside ``kb_id``.
    """

    def __init__(
        self,
        s3: S3DataAccess,
        kb_id: str = '',
        ds_id: str = '',
    ):
        self.s3 = s3
        self.kb_id = kb_id
        self.ds_id = ds_id

        # Create bedrock-agent client only when KB config is present.
        # Per-call creation is unnecessary — Lambda execution environments
        # reuse clients across warm starts.
        self._bedrock_agent: Optional[Any] = None
        if kb_id and ds_id:
            self._bedrock_agent = boto3.client('bedrock-agent')

    def list_standards(self) -> Dict[str, Any]:
        """List all standards in the bucket with their metadata.

        Paginates through ``list_objects_v2``, collects content files
        (excluding metadata sidecars), and reads each sidecar if present.
        Supports any file format — not limited to ``.md``.

        Returns:
            Dict with ``standards`` list, ``count``, and ``bucket``.
        """
        standards: List[Dict[str, Any]] = []
        paginator = self.s3.client.get_paginator('list_objects_v2')

        content_objects: List[Dict[str, Any]] = []
        sidecar_keys: set[str] = set()

        for page in paginator.paginate(Bucket=self.s3.bucket_name):
            for obj in page.get('Contents', []):
                key: str = obj['Key']
                if key.endswith('.metadata.json'):
                    sidecar_keys.add(key)
                else:
                    content_objects.append(obj)

        for obj in content_objects:
            key = obj['Key']
            sidecar_key = f"{key}.metadata.json"
            has_metadata = sidecar_key in sidecar_keys

            # Derive standard_id from the directory name (first path segment)
            parts = key.split('/')
            standard_id = parts[0] if len(parts) > 1 else key.rsplit('.', 1)[0]

            entry: Dict[str, Any] = {
                'key': key,
                'standard_id': standard_id,
                'size_bytes': obj.get('Size', 0),
                'last_modified': obj['LastModified'].isoformat() if hasattr(obj['LastModified'], 'isoformat') else str(obj['LastModified']),
                'has_metadata': has_metadata,
            }

            if has_metadata:
                entry.update(self._read_sidecar(sidecar_key))

            standards.append(entry)

        standards.sort(key=lambda s: (s['standard_id'], s['key']))

        return {
            'standards': standards,
            'count': len(standards),
            'bucket': self.s3.bucket_name,
        }

    def _read_sidecar(self, sidecar_key: str) -> Dict[str, Any]:
        """Read and parse a metadata sidecar JSON file.

        Args:
            sidecar_key: S3 key of the ``.metadata.json`` sidecar.

        Returns:
            Dict of sidecar fields to merge into the standard entry.
            Returns empty dict on read/parse failure (metadata is optional).
        """
        try:
            raw = self.s3.get_document_content(sidecar_key)
            data = json.loads(raw)

            # Extract known fields from the Bedrock metadata sidecar format.
            # Sidecars use ``metadataAttributes`` with typed values.
            result: Dict[str, Any] = {}
            attrs = data.get('metadataAttributes', {})
            for attr_key, attr_val in attrs.items():
                if not isinstance(attr_val, dict):
                    result[attr_key] = attr_val
                    continue
                # Bedrock sidecar format nests: {"value": {"type": "STRING", "stringValue": "..."}}
                inner = attr_val.get('value', attr_val)
                if isinstance(inner, dict):
                    # Extract the typed value (stringValue, numberValue, booleanValue, etc.)
                    for typed_key in ('stringValue', 'numberValue', 'booleanValue', 'stringListValue'):
                        if typed_key in inner:
                            result[attr_key] = inner[typed_key]
                            break
                    else:
                        result[attr_key] = str(inner)
                else:
                    result[attr_key] = inner

            return result
        except Exception as e:
            logger.warning("Failed to read sidecar %s: %s", sidecar_key, e)
            return {}

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def upload_standard(
        self,
        standard_id: str,
        source_type: str,
        filename: str,
        jurisdiction: str = '',
        industry: str = '',
        content_type: str = 'application/octet-stream',
    ) -> Dict[str, Any]:
        """Validate inputs, write the metadata sidecar, and return a pre-signed upload URL.

        The caller uploads the content file to the returned URL. The sidecar is
        written server-side to guarantee it matches the Bedrock metadata schema.
        The original file extension is preserved in the S3 key.

        Args:
            standard_id: Kebab-case identifier (e.g. ``cps-230``).
            source_type: One of :data:`VALID_SOURCE_TYPES`.
            filename: Original filename — its extension is used for the S3 key.
            jurisdiction: One of :data:`VALID_JURISDICTIONS`. Optional.
            industry: One of :data:`VALID_INDUSTRIES`. Optional.
            content_type: MIME type for the pre-signed URL.

        Returns:
            Dict with ``upload_url``, ``s3_key``, and ``metadata_written``.

        Raises:
            ValueError: If any field fails validation.
        """
        self._validate_standard_id(standard_id)
        self._validate_source_type(source_type)
        if jurisdiction:
            self._validate_jurisdiction(jurisdiction)
        if industry:
            self._validate_industry(industry)

        # Preserve the original file extension (e.g. .md, .pdf, .txt)
        _, ext = os.path.splitext(filename)
        if not ext:
            ext = '.md'
        s3_key = f"{standard_id}/{standard_id}{ext}"
        sidecar_key = f"{s3_key}.metadata.json"

        sidecar = self._build_sidecar(standard_id, source_type, jurisdiction, industry)
        self.s3.put_document(sidecar_key, json.dumps(sidecar, indent=2), content_type='application/json')
        logger.info("Wrote metadata sidecar for standard '%s' (%s)", standard_id, filename)

        upload_url = self.s3.generate_upload_url(s3_key, content_type=content_type)

        return {
            'upload_url': upload_url,
            's3_key': s3_key,
            'metadata_written': True,
        }

    def delete_standard(self, standard_id: str) -> Dict[str, Any]:
        """Delete all objects under the standard's S3 prefix.

        Verifies the standard exists before deleting. Returns the count
        of objects removed.

        Args:
            standard_id: Kebab-case identifier.

        Returns:
            Dict with ``standard_id`` and ``objects_deleted`` count.

        Raises:
            ValueError: If ``standard_id`` is invalid or the standard doesn't exist.
        """
        self._validate_standard_id(standard_id)

        # Verify the standard exists before attempting delete
        self._find_content_key(standard_id)

        prefix = f"{standard_id}/"
        deleted = self.s3.delete_prefix(prefix)
        logger.info("Deleted %d objects for standard '%s'", deleted, standard_id)
        return {
            'standard_id': standard_id,
            'objects_deleted': deleted,
        }

    def update_metadata(
        self,
        standard_id: str,
        source_type: str,
        jurisdiction: str = '',
        industry: str = '',
    ) -> Dict[str, Any]:
        """Rewrite the metadata sidecar without touching the content file.

        Validates all fields, discovers the actual content file under the
        standard's prefix, then overwrites the sidecar JSON in S3.

        Args:
            standard_id: Kebab-case identifier of an existing standard.
            source_type: One of :data:`VALID_SOURCE_TYPES`.
            jurisdiction: One of :data:`VALID_JURISDICTIONS`. Optional.
            industry: One of :data:`VALID_INDUSTRIES`. Optional.

        Returns:
            Dict with ``standard_id`` and ``metadata_written``.

        Raises:
            ValueError: If any field fails validation or the standard doesn't exist.
        """
        self._validate_standard_id(standard_id)
        self._validate_source_type(source_type)
        if jurisdiction:
            self._validate_jurisdiction(jurisdiction)
        if industry:
            self._validate_industry(industry)

        # Discover the actual content file — don't assume filename or extension
        content_key = self._find_content_key(standard_id)

        sidecar_key = f"{content_key}.metadata.json"
        sidecar = self._build_sidecar(standard_id, source_type, jurisdiction, industry)
        self.s3.put_document(sidecar_key, json.dumps(sidecar, indent=2), content_type='application/json')
        logger.info("Updated metadata sidecar for standard '%s' (content: %s)", standard_id, content_key)

        return {
            'standard_id': standard_id,
            'metadata_written': True,
        }

    # ------------------------------------------------------------------
    # KB sync operations
    # ------------------------------------------------------------------

    def start_sync(self) -> Dict[str, Any]:
        """Trigger a Bedrock KB ingestion job.

        Returns:
            Dict with ``ingestion_job_id`` and ``status``.

        Raises:
            RuntimeError: If KB configuration is missing.
            ClientError: If the Bedrock API call fails.
        """
        if not self._bedrock_agent:
            raise RuntimeError('Standards KB not configured — cannot start sync')

        response = self._bedrock_agent.start_ingestion_job(
            knowledgeBaseId=self.kb_id,
            dataSourceId=self.ds_id,
        )
        job = response['ingestionJob']
        logger.info("Started ingestion job %s for KB %s", job['ingestionJobId'], self.kb_id)
        return {
            'ingestion_job_id': job['ingestionJobId'],
            'status': job['status'],
        }

    def get_sync_status(self) -> Dict[str, Any]:
        """Get the status of the most recent ingestion job.

        Returns:
            Dict with ``status``, ``ingestion_job_id``, timestamps, and
            ``statistics`` (when the job is complete).

        Raises:
            RuntimeError: If KB configuration is missing.
            ClientError: If the Bedrock API call fails.
        """
        if not self._bedrock_agent:
            raise RuntimeError('Standards KB not configured — cannot get sync status')

        response = self._bedrock_agent.list_ingestion_jobs(
            knowledgeBaseId=self.kb_id,
            dataSourceId=self.ds_id,
            maxResults=1,
            sortBy={'attribute': 'STARTED_AT', 'order': 'DESCENDING'},
        )
        jobs = response.get('ingestionJobSummaries', [])
        if not jobs:
            return {'status': 'NO_JOBS', 'ingestion_job_id': None}

        job = jobs[0]
        result: Dict[str, Any] = {
            'status': job['status'],
            'ingestion_job_id': job['ingestionJobId'],
            'started_at': job.get('startedAt', ''),
        }

        # Include completion time and statistics when available
        if 'updatedAt' in job and job['status'] in ('COMPLETE', 'FAILED'):
            result['completed_at'] = job['updatedAt']
        if 'statistics' in job:
            stats = job['statistics']
            result['statistics'] = {
                'documents_scanned': stats.get('numberOfDocumentsScanned', 0),
                'documents_indexed': stats.get('numberOfNewDocumentsIndexed', 0)
                + stats.get('numberOfModifiedDocumentsIndexed', 0),
                'documents_failed': stats.get('numberOfDocumentsFailed', 0),
            }

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_content_key(self, standard_id: str) -> str:
        """Find the actual content file key under a standard's S3 prefix.

        Lists objects under ``{standard_id}/`` and returns the first key
        that is not a metadata sidecar. This avoids hardcoding the file
        extension — works for ``.md``, ``.pdf``, ``.txt``, etc.

        Args:
            standard_id: Kebab-case identifier.

        Returns:
            The S3 key of the content file.

        Raises:
            ValueError: If no content file exists under the prefix.
        """
        prefix = f"{standard_id}/"
        response = self.s3.client.list_objects_v2(
            Bucket=self.s3.bucket_name,
            Prefix=prefix,
            MaxKeys=20,
        )
        for obj in response.get('Contents', []):
            key: str = obj['Key']
            if not key.endswith('.metadata.json'):
                return key

        raise ValueError(
            f"Standard '{standard_id}' not found — no content file under {prefix}"
        )

    @staticmethod
    def _validate_standard_id(standard_id: str) -> None:
        """Validate that ``standard_id`` is kebab-case and within length limits.

        Raises:
            ValueError: If the identifier is invalid.
        """
        if not standard_id or len(standard_id) > 100:
            raise ValueError('standard_id must be 1-100 characters')
        if not _STANDARD_ID_RE.match(standard_id):
            raise ValueError(
                'standard_id must be kebab-case (lowercase alphanumeric + hyphens, '
                'no leading/trailing/consecutive hyphens)'
            )

    @staticmethod
    def _validate_source_type(source_type: str) -> None:
        """Validate ``source_type`` against the allowed vocabulary.

        Raises:
            ValueError: If the value is not in :data:`VALID_SOURCE_TYPES`.
        """
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{source_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}"
            )

    @staticmethod
    def _validate_jurisdiction(jurisdiction: str) -> None:
        """Validate ``jurisdiction`` against the allowed vocabulary.

        Raises:
            ValueError: If the value is not in :data:`VALID_JURISDICTIONS`.
        """
        if jurisdiction not in VALID_JURISDICTIONS:
            raise ValueError(
                f"Invalid jurisdiction '{jurisdiction}'. "
                f"Must be one of: {', '.join(sorted(VALID_JURISDICTIONS))}"
            )

    @staticmethod
    def _validate_industry(industry: str) -> None:
        """Validate ``industry`` against the allowed vocabulary.

        Raises:
            ValueError: If the value is not in :data:`VALID_INDUSTRIES`.
        """
        if industry not in VALID_INDUSTRIES:
            raise ValueError(
                f"Invalid industry '{industry}'. "
                f"Must be one of: {', '.join(sorted(VALID_INDUSTRIES))}"
            )

    @staticmethod
    def _build_sidecar(
        standard_id: str,
        source_type: str,
        jurisdiction: str = '',
        industry: str = '',
    ) -> Dict[str, Any]:
        """Build a Bedrock metadata sidecar in the doubly-nested format.

        The format is::

            {
              "metadataAttributes": {
                "standard_id": {
                  "value": {"type": "STRING", "stringValue": "cps-230"}
                },
                ...
              }
            }

        Only includes ``jurisdiction`` and ``industry`` when non-empty.

        Args:
            standard_id: Standard identifier.
            source_type: Source type value.
            jurisdiction: Jurisdiction code (e.g. ``AU``). Optional.
            industry: Industry sector (e.g. ``financial_services``). Optional.

        Returns:
            Sidecar dict ready for JSON serialization.
        """
        attrs: Dict[str, Any] = {
            'standard_id': {
                'value': {'type': 'STRING', 'stringValue': standard_id},
            },
            'source_type': {
                'value': {'type': 'STRING', 'stringValue': source_type},
            },
        }
        if jurisdiction:
            attrs['jurisdiction'] = {
                'value': {'type': 'STRING', 'stringValue': jurisdiction},
            }
        if industry:
            attrs['industry'] = {
                'value': {'type': 'STRING', 'stringValue': industry},
            }
        return {'metadataAttributes': attrs}
