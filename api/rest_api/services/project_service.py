"""Project business logic."""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

import boto3

from ..data_access import DynamoDBDataAccess, S3DataAccess

logger = logging.getLogger(__name__)


class ProjectService:
    """Handles project business logic."""
    
    def __init__(self, dynamodb: DynamoDBDataAccess, s3: S3DataAccess):
        """Initialize project service.
        
        Args:
            dynamodb: DynamoDB data access instance
            s3: S3 data access instance
        """
        self.dynamodb = dynamodb
        self.s3 = s3
    
    def create_project(self, name: str, description: str = '', created_by: str = '',
                       created_by_email: str = '',
                       context_id: str = '', files: list = None) -> Dict[str, Any]:
        """Create a new project with pre-signed upload URLs.

        Args:
            name: Project name
            description: Project description
            created_by: Cognito user sub
            created_by_email: Cognito user email
            context_id: Optional organizational context ID
            files: List of dicts with 'filename' keys. Required — at least one file.

        Returns:
            Project details with upload URLs

        Raises:
            ValueError: If files list is empty or missing.
        """
        if not files:
            raise ValueError('At least one file is required. Provide a "files" array with filename entries.')

        for f in files:
            if not f.get('filename'):
                raise ValueError('Each file must have a filename.')

        project_id = str(uuid.uuid4())[:8]
        upload_expires_at = (datetime.now(tz=timezone.utc) + timedelta(minutes=15)).isoformat()

        file_keys = []
        file_manifest = []
        for f in files:
            filename = f['filename']
            safe_name = filename.replace(' ', '_')
            s3_key = f"projects/{project_id}/files/{safe_name}"
            file_keys.append({
                's3_key': s3_key,
                'filename': filename,
                'content_type': f.get('content_type', 'application/octet-stream'),
            })
            file_manifest.append({
                's3_key': s3_key,
                'filename': filename,
            })

        upload_urls = self.s3.generate_upload_urls(file_keys, expires_in=900)

        # First file's s3_key serves as the canonical key in the project record
        canonical_s3_key = file_keys[0]['s3_key']

        project = self.dynamodb.create_project(
            project_id=project_id,
            name=name,
            description=description,
            s3_bucket=self.s3.bucket_name,
            s3_key=canonical_s3_key,
            created_by=created_by,
            created_by_email=created_by_email,
            context_id=context_id,
            files=file_manifest,
        )

        return {
            'project_id': project_id,
            'name': name,
            'status': 'pending',
            'upload_urls': upload_urls,
            'upload_expires_at': upload_expires_at,
            'created_at': project['created_at'],
        }
    
    def list_projects(self, status_filter: str = None, limit: int = 50) -> Dict[str, Any]:
        """List all projects, optionally filtered by status.
        
        Args:
            status_filter: Optional status to filter by
            limit: Maximum number of projects to return
            
        Returns:
            List of projects with count
        """
        projects = self.dynamodb.list_projects(status_filter, limit)
        
        # Format projects for response with enriched data
        formatted_projects = []
        for item in projects:
            project = {
                'project_id': item['project_id'],
                'name': item['name'],
                'description': item.get('description', ''),
                'status': item['status'],
                'created_at': item['created_at'],
                'updated_at': item['updated_at'],
                'created_by_email': item.get('created_by_email', ''),
                'latest_review_id': item.get('latest_review_id', ''),
            }

            # File info
            files = item.get('files', [])
            if files:
                project['file_count'] = len(files)
                project['file_names'] = [f.get('filename', '') for f in files]
            else:
                project['file_count'] = 1
                s3_key = item.get('s3_key', '')
                project['file_names'] = [s3_key.split('/')[-1]] if s3_key else []

            formatted_projects.append(project)

        return {
            'projects': formatted_projects,
            'count': len(formatted_projects)
        }

    def list_projects_for_user(self, user_sub: str, limit: int = 50) -> Dict[str, Any]:
        """List projects owned by a specific user.

        Uses GSI2 for an efficient per-user query with no FilterExpression.

        Args:
            user_sub: Cognito user sub to filter by.
            limit: Maximum number of projects to return.

        Returns:
            Dict with projects list and count.
        """
        projects = self.dynamodb.list_projects_for_user(user_sub, limit)

        formatted_projects = []
        for item in projects:
            project = {
                'project_id': item['project_id'],
                'name': item['name'],
                'description': item.get('description', ''),
                'status': item['status'],
                'created_at': item['created_at'],
                'updated_at': item['updated_at'],
                'created_by_email': item.get('created_by_email', ''),
                'latest_review_id': item.get('latest_review_id', ''),
            }

            files = item.get('files', [])
            if files:
                project['file_count'] = len(files)
                project['file_names'] = [f.get('filename', '') for f in files]
            else:
                project['file_count'] = 1
                s3_key = item.get('s3_key', '')
                project['file_names'] = [s3_key.split('/')[-1]] if s3_key else []

            formatted_projects.append(project)

        return {
            'projects': formatted_projects,
            'count': len(formatted_projects),
        }

    def verify_project_ownership(self, project_id: str, user_sub: str) -> Dict[str, Any]:
        """Verify the requesting user owns the project.

        Args:
            project_id: Project identifier.
            user_sub: Cognito user sub from JWT.

        Returns:
            Raw project item if the user owns it.

        Raises:
            KeyError: If the project does not exist.
            PermissionError: If the user does not own the project.
        """
        return self.dynamodb.verify_project_ownership(project_id, user_sub)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get project details including latest review.
        
        Args:
            project_id: Project identifier
            
        Returns:
            Project details or None if not found
        """
        # Get project metadata
        project = self.dynamodb.get_project(project_id)
        if not project:
            return None
        
        # Get latest review (if exists)
        review = self.dynamodb.get_latest_review(project_id)
        
        # Build response
        result = {
            'project_id': project['project_id'],
            'name': project['name'],
            'description': project.get('description', ''),
            'status': project['status'],
            'context_id': project.get('context_id', ''),
            'created_at': project['created_at'],
            'updated_at': project['updated_at'],
            'error_message': project.get('error_message', ''),
            'latest_review_id': project.get('latest_review_id', ''),
        }
        
        if project.get('s3_key'):
            result['document'] = {
                's3_bucket': project['s3_bucket'],
                's3_key': project['s3_key'],
                'name': project.get('document_name', ''),
                'size': project.get('document_size', 0)
            }
        
        if review:
            result['review'] = {
                'review_id': review.get('review_id'),
                'status': review.get('status'),
                'result': review.get('findings'),
                'created_at': review.get('created_at'),
                'duration_ms': review.get('duration_ms')
            }
        
        return result
    def get_project_document(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get the uploaded design document(s) — text content or pre-signed URLs.

        For text files, returns inline content. For binary files (PDFs),
        returns a pre-signed download URL so the browser can open them directly.

        Args:
            project_id: Project identifier

        Returns:
            Dict with project_id and files list, or None if project not found
        """
        project = self.dynamodb.get_project(project_id)
        if not project:
            return None

        files = project.get('files', [])
        if not files:
            return {'project_id': project_id, 'error': 'No files found for this project'}

        result_files = []
        for f in files:
            s3_key = f.get('s3_key', '')
            filename = f.get('filename', s3_key.split('/')[-1])
            try:
                content = self.s3.get_document_content(s3_key)
                result_files.append({'filename': filename, 'content': content})
            except UnicodeDecodeError:
                # Binary file — return a pre-signed URL instead
                url = self.s3.generate_download_url(s3_key)
                result_files.append({'filename': filename, 'download_url': url})
        return {
            'project_id': project_id,
            'files': result_files,
        }

    def delete_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Delete a project and all associated data.

        Cleans up: DynamoDB items, S3 documents, AgentCore Memory records.

        Args:
            project_id: Project identifier

        Returns:
            Deletion summary or None if project not found
        """
        # Verify project exists
        project = self.dynamodb.get_project(project_id)
        if not project:
            return None

        # Delete all S3 objects under the project prefix
        s3_deleted = self.s3.delete_prefix(f"projects/{project_id}/")

        # Delete all DynamoDB items for this project
        items_deleted = self.dynamodb.delete_project(project_id)

        # Delete AgentCore Memory records for this project
        memory_deleted = self._delete_memory_records(project_id)

        # Delete indexed document chunks from the Document Index KB
        kb_deleted = self._delete_kb_documents(project_id)

        return {
            'project_id': project_id,
            'items_deleted': items_deleted,
            'documents_deleted': s3_deleted,
            'memory_records_deleted': memory_deleted,
            'kb_documents_deleted': kb_deleted,
        }

    def _delete_memory_records(self, project_id: str) -> int:
        """Delete all AgentCore Memory records for a project.

        Lists records under the /findings/{project_id} namespace prefix,
        then batch-deletes them.

        Args:
            project_id: Project identifier

        Returns:
            Number of memory records deleted

        Raises:
            RuntimeError: If the AgentCore client can't be created or
                listing/deleting records fails.
        """
        memory_arn = os.environ.get('SHARED_MEMORY_ARN', '')
        if not memory_arn:
            return 0

        memory_id = memory_arn.split('/')[-1]
        client = boto3.client('bedrock-agentcore')

        deleted = 0
        namespace = f"/findings/{project_id}"

        next_token = None
        record_ids = []

        # List all records under the project namespace
        while True:
            kwargs = {
                'memoryId': memory_id,
                'namespace': namespace,
                'maxResults': 100,
            }
            if next_token:
                kwargs['nextToken'] = next_token

            resp = client.list_memory_records(**kwargs)
            for record in resp.get('memoryRecordSummaries', []):
                rid = record.get('memoryRecordId')
                if rid:
                    record_ids.append(rid)

            next_token = resp.get('nextToken')
            if not next_token:
                break

        # Batch delete in chunks of 100
        for i in range(0, len(record_ids), 100):
            batch = [{'memoryRecordId': rid} for rid in record_ids[i:i + 100]]
            resp = client.batch_delete_memory_records(
                memoryId=memory_id, records=batch,
            )
            deleted += len(resp.get('successfulRecords', []))
            failed = resp.get('failedRecords', [])
            if failed:
                failed_ids = [f.get('memoryRecordId') for f in failed]
                raise RuntimeError(
                    f"Failed to delete {len(failed)} memory records for "
                    f"project {project_id}: {failed_ids}"
                )

        return deleted

    def _delete_kb_documents(self, project_id: str) -> int:
        """Delete indexed document chunks from the Document Index KB.

        Lists documents in the KB data source, filters by project_id
        prefix in the custom document identifier, and deletes matches.

        Args:
            project_id: Project identifier.

        Returns:
            Number of KB documents deleted. Returns 0 if the Document
            KB is not configured.
        """
        document_kb_id = os.environ.get('DOCUMENT_KB_ID', '')
        document_ds_id = os.environ.get('DOCUMENT_DS_ID', '')
        if not document_kb_id or not document_ds_id:
            return 0

        try:
            client = boto3.client('bedrock-agent')
            response = client.list_knowledge_base_documents(
                knowledgeBaseId=document_kb_id,
                dataSourceId=document_ds_id,
                maxResults=100,
            )

            to_delete = []
            for doc in response.get('documentDetails', []):
                identifier = doc.get('identifier', {}).get('custom', {}).get('id', '')
                if identifier.startswith(f'{project_id}-'):
                    to_delete.append({
                        'custom': {'id': identifier},
                        'dataSourceType': 'CUSTOM',
                    })

            if not to_delete:
                return 0

            resp = client.delete_knowledge_base_documents(
                knowledgeBaseId=document_kb_id,
                dataSourceId=document_ds_id,
                documentIdentifiers=to_delete,
            )
            deleted = len(resp.get('documentDetails', []))
            logger.info(
                "Deleted %d KB document(s) for project %s",
                deleted,
                project_id,
            )
            return deleted
        except Exception:
            logger.warning(
                "Failed to delete KB documents for project %s — continuing",
                project_id,
                exc_info=True,
            )
            return 0
