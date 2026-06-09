"""S3 data access operations."""
import os
from typing import Dict, Any
import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError


class S3DataAccess:
    """Handles all S3 operations for document storage."""
    
    def __init__(self, bucket_name: str = None):
        """Initialize S3 data access.
        
        Args:
            bucket_name: S3 bucket name. If None, reads from environment.
        """
        self.bucket_name = bucket_name or os.environ['S3_BUCKET_NAME']
        self.client = boto3.client(
            's3',
            config=BotoConfig(
                signature_version='s3v4',
                s3={'addressing_style': 'virtual'},
            ),
        )
    
    def generate_upload_url(self, s3_key: str, expires_in: int = 900,
                           content_type: str = 'application/octet-stream') -> str:
        """Generate a pre-signed URL for uploading a document.
        
        Args:
            s3_key: S3 key for the document
            expires_in: URL expiration time in seconds (default: 15 minutes)
            content_type: MIME type for the upload
            
        Returns:
            Pre-signed upload URL
        """
        url = self.client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': self.bucket_name,
                'Key': s3_key,
                'ContentType': content_type
            },
            ExpiresIn=expires_in
        )
        return url
    def generate_download_url(self, s3_key: str, expires_in: int = 900) -> str:
        """Generate a pre-signed URL for downloading/viewing a document.

        Args:
            s3_key: S3 key for the document
            expires_in: URL expiration time in seconds (default: 15 minutes)

        Returns:
            Pre-signed download URL
        """
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket_name, 'Key': s3_key},
            ExpiresIn=expires_in,
        )
    
    def document_exists(self, s3_key: str) -> bool:
        """Check if a document exists in S3.
        
        Args:
            s3_key: S3 key for the document
            
        Returns:
            True if document exists, False otherwise
        """
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
    def delete_document(self, s3_key: str) -> None:
        """Delete a document from S3.

        Args:
            s3_key: S3 key for the document.

        Raises:
            ClientError: If the delete fails.
        """
        self.client.delete_object(Bucket=self.bucket_name, Key=s3_key)

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under an S3 prefix.

        Args:
            prefix: S3 key prefix (e.g. 'projects/abc123/')

        Returns:
            Number of objects deleted
        """
        deleted = 0
        paginator = self.client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            objects = page.get('Contents', [])
            if not objects:
                continue
            delete_keys = [{'Key': obj['Key']} for obj in objects]
            self.client.delete_objects(
                Bucket=self.bucket_name,
                Delete={'Objects': delete_keys, 'Quiet': True},
            )
            deleted += len(delete_keys)
        return deleted
    def put_document(self, s3_key: str, content: str, content_type: str = 'text/markdown') -> None:
        """Write text content directly to S3.

        Args:
            s3_key: S3 key for the document.
            content: Text content to write.
            content_type: MIME type.

        Raises:
            ClientError: If the write fails.
        """
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=content.encode('utf-8'),
            ContentType=content_type,
        )

    def get_document_content(self, s3_key: str) -> str:
        """Read text content from S3.

        Args:
            s3_key: S3 key for the document

        Returns:
            Document text content.

        Raises:
            ClientError: If the S3 read fails.
            UnicodeDecodeError: If the content is not valid UTF-8.
        """
        obj = self.client.get_object(Bucket=self.bucket_name, Key=s3_key)
        return obj['Body'].read().decode('utf-8')
    def generate_upload_urls(self, file_keys: list, expires_in: int = 900) -> list:
        """Generate pre-signed URLs for multiple file uploads.

        Args:
            file_keys: List of dicts with 's3_key' and optional 'content_type'
            expires_in: URL expiration time in seconds

        Returns:
            List of dicts with 's3_key' and 'upload_url'
        """
        results = []
        for fk in file_keys:
            s3_key = fk['s3_key']
            ct = fk.get('content_type', 'application/octet-stream')
            url = self.generate_upload_url(s3_key, expires_in=expires_in, content_type=ct)
            results.append({'s3_key': s3_key, 'upload_url': url, 'filename': fk.get('filename', '')})
        return results
    
    def get_document_metadata(self, s3_key: str) -> Dict[str, Any]:
        """Get document metadata from S3.
        
        Args:
            s3_key: S3 key for the document
            
        Returns:
            Document metadata (size, content-type, etc.)
        """
        response = self.client.head_object(Bucket=self.bucket_name, Key=s3_key)
        return {
            'size': response['ContentLength'],
            'content_type': response.get('ContentType', 'application/octet-stream'),
            'last_modified': response['LastModified'].isoformat()
        }
