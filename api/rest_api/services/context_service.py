"""Context document business logic."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from ..data_access import DynamoDBDataAccess, S3DataAccess


class ContextService:
    """Handles organizational context document business logic."""

    def __init__(self, dynamodb: DynamoDBDataAccess, s3: S3DataAccess):
        self.dynamodb = dynamodb
        self.s3 = s3

    def create_context(self, name: str, description: str = '',
                       created_by: str = '') -> Dict[str, Any]:
        """Create a new context document with pre-signed upload URL."""
        context_id = str(uuid.uuid4())[:8]
        s3_key = f"contexts/{context_id}/document.md"

        upload_url = self.s3.generate_upload_url(s3_key, expires_in=900, content_type='text/markdown')
        upload_expires_at = (datetime.now(tz=timezone.utc) + timedelta(minutes=15)).isoformat()

        context = self.dynamodb.create_context(
            context_id=context_id,
            name=name,
            description=description,
            s3_bucket=self.s3.bucket_name,
            s3_key=s3_key,
            created_by=created_by,
        )

        return {
            'context_id': context_id,
            'name': name,
            'description': description,
            'upload_url': upload_url,
            'upload_expires_at': upload_expires_at,
            'created_at': context['created_at'],
        }

    def list_contexts(self, limit: int = 50) -> Dict[str, Any]:
        """List all context documents."""
        contexts = self.dynamodb.list_contexts(limit)
        formatted = []
        for item in contexts:
            formatted.append({
                'context_id': item['context_id'],
                'name': item['name'],
                'description': item.get('description', ''),
                'created_at': item['created_at'],
            })
        return {'contexts': formatted, 'count': len(formatted)}

    def get_context(self, context_id: str) -> Optional[Dict[str, Any]]:
        """Get context document details."""
        context = self.dynamodb.get_context(context_id)
        if not context:
            return None
        return {
            'context_id': context['context_id'],
            'name': context['name'],
            'description': context.get('description', ''),
            's3_bucket': context.get('s3_bucket', ''),
            's3_key': context.get('s3_key', ''),
            'created_at': context['created_at'],
        }

    def delete_context(self, context_id: str) -> Optional[Dict[str, Any]]:
        """Delete a context document."""
        context = self.dynamodb.get_context(context_id)
        if not context:
            return None
        s3_key = context.get('s3_key')
        if s3_key:
            self.s3.delete_document(s3_key)
        self.dynamodb.delete_context(context_id)
        return {'context_id': context_id, 'deleted': True}

    def get_context_content(self, context_id: str) -> Optional[str]:
        """Load the actual context document text from S3.

        Args:
            context_id: Context identifier.

        Returns:
            The context document text, or None if the context doesn't exist
            or has no S3 key.

        Raises:
            ClientError: If the S3 read fails.
        """
        context = self.dynamodb.get_context(context_id)
        if not context or not context.get('s3_key'):
            return None
        return self.s3.get_document_content(context['s3_key'])

    def update_context_content(self, context_id: str, content: str) -> Optional[Dict[str, Any]]:
        """Update the context document content in S3.

        Args:
            context_id: Context identifier.
            content: New document text.

        Returns:
            Confirmation dict, or None if the context doesn't exist.

        Raises:
            ClientError: If the S3 write fails.
        """
        context = self.dynamodb.get_context(context_id)
        if not context or not context.get('s3_key'):
            return None
        self.s3.put_document(context['s3_key'], content)
        return {'context_id': context_id, 'updated': True}
