"""Request and response parsers.

Pure functions for parsing API Gateway events, DynamoDB items, and
AgentCore responses. No AWS client dependencies — S3 reads happen
at the call site, not here.
"""
import json
import logging
from decimal import Decimal
from typing import Dict, Any

logger = logging.getLogger(__name__)


def parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse request body from API Gateway event.
    
    Args:
        event: API Gateway event
        
    Returns:
        Parsed body as dict
    """
    body = event.get('body')
    if isinstance(body, str):
        return json.loads(body)
    if isinstance(body, dict):
        return body
    return event


def decimal_to_number(obj):
    """Convert Decimal objects to int or float for JSON serialization.
    
    Args:
        obj: Object to convert (can be dict, list, or Decimal)
        
    Returns:
        Converted object with Decimals as int/float
    """
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_number(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_number(i) for i in obj]
    return obj


def deserialize_review(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw REVIEW# item from DynamoDB.

    Findings are stored in S3 and referenced via ``findings_s3_bucket`` and
    ``findings_s3_key``. The caller is responsible for hydrating findings
    from S3 before calling this function (see ``get_latest_review``).

    This function handles the no-S3-reference case by defaulting
    ``findings`` to ``{}``.

    Args:
        item: Raw DynamoDB item.

    Returns:
        The item, potentially with ``findings`` defaulted to ``{}``.

    Raises:
        ValueError: If the item has an S3 reference but ``findings`` was
            not hydrated by the caller.
    """
    s3_bucket = item.get('findings_s3_bucket', '')
    s3_key = item.get('findings_s3_key', '')

    if s3_bucket and s3_key:
        if 'findings' not in item:
            raise ValueError(
                f"Item has S3 reference s3://{s3_bucket}/{s3_key} but 'findings' "
                f"was not hydrated by the caller. Use s3.read_json() before "
                f"calling deserialize_review()."
            )
    else:
        item.setdefault('findings', {})

    return item
