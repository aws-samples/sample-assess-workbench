"""Project and context metadata lookups.

Shared functions for retrieving project and context records from DynamoDB.
Used by workflow Lambdas and the WebSocket handler.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_project(table, project_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a project's METADATA item from DynamoDB.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.

    Returns:
        The project item dict, or None if not found.

    Raises:
        Exception: Propagates any DynamoDB read errors.
    """
    response = table.get_item(
        Key={'PK': f'PROJECT#{project_id}', 'SK': 'METADATA'}
    )
    return response.get('Item')


def get_context_metadata(table, context_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a context's METADATA item from DynamoDB.

    Args:
        table: boto3 DynamoDB Table resource.
        context_id: Context identifier.

    Returns:
        The context item dict, or None if not found.

    Raises:
        Exception: Propagates any DynamoDB read errors.
    """
    response = table.get_item(
        Key={'PK': f'CONTEXT#{context_id}', 'SK': 'METADATA'}
    )
    return response.get('Item')
