"""HTTP response builders."""
import json
import os
from typing import Any, Dict
from .parsers import decimal_to_number

# CORS origin — configurable via environment variable, defaults to * for dev
_ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', '*')

# Security headers applied to every response
_SECURITY_HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': _ALLOWED_ORIGIN,
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'none'",
    'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
}


def success_response(data: Any, status_code: int = 200) -> Dict[str, Any]:
    """Build success response.
    
    Args:
        data: Response data (will be JSON serialized)
        status_code: HTTP status code (default: 200)
        
    Returns:
        API Gateway response dict
    """
    # Convert Decimal types to int/float for JSON serialization
    data = decimal_to_number(data)
    
    return {
        'statusCode': status_code,
        'headers': {**_SECURITY_HEADERS},
        'body': json.dumps(data)
    }


def error_response(status_code: int, error: str, details: str = None) -> Dict[str, Any]:
    """Build error response.
    
    Args:
        status_code: HTTP status code
        error: Error message
        details: Optional error details (only included for 4xx responses)
        
    Returns:
        API Gateway response dict
    """
    body = {'error': error}
    # Only include details for client errors (4xx) — never leak internals on 5xx
    if details and status_code < 500:
        body['details'] = details
    
    return {
        'statusCode': status_code,
        'headers': {**_SECURITY_HEADERS},
        'body': json.dumps(body)
    }
