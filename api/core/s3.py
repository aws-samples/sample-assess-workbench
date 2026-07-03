"""Centralized S3 operations for Risk Assessor Lambdas.

Provides typed, well-logged helpers for the three S3 access patterns
used across the codebase:

- read_json:  GET an object and parse as JSON (findings, documents, contexts)
- write_json: PUT a JSON-serializable object
- read_text:  GET an object and decode as UTF-8 text

All functions raise on failure — no silent fallbacks, no empty defaults.
Callers decide how to handle errors.

The module manages a single lazy-initialized S3 client. All Lambdas in the
shared layer share this client within a given execution environment.
"""

import json
import logging
from typing import Any

import boto3

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    """Return the module-level S3 client, creating it on first use."""
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def read_json(bucket: str, key: str) -> Any:
    """Read an S3 object and parse its body as JSON.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        The parsed JSON value (dict, list, etc.).

    Raises:
        RuntimeError: If the S3 read or JSON parse fails. The original
            exception is chained for diagnostics.
    """
    try:
        obj = _get_client().get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read().decode("utf-8")
        return json.loads(body)
    except Exception as e:
        raise RuntimeError(f"Failed to read JSON from s3://{bucket}/{key}: {e}") from e


def write_json(bucket: str, key: str, data: Any) -> None:
    """Serialize data as JSON and write to S3.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        data: JSON-serializable value.

    Raises:
        RuntimeError: If the S3 write fails.
    """
    try:
        _get_client().put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as e:
        raise RuntimeError(f"Failed to write JSON to s3://{bucket}/{key}: {e}") from e


def read_text(bucket: str, key: str) -> str:
    """Read an S3 object and return its body as a UTF-8 string.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        The object body decoded as UTF-8.

    Raises:
        RuntimeError: If the S3 read or decode fails.
    """
    try:
        obj = _get_client().get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to read text from s3://{bucket}/{key}: {e}") from e


def head_object(bucket: str, key: str) -> dict:
    """Return the metadata (HEAD) for an S3 object.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        The HEAD response dict (ContentLength, ContentType, etc.).

    Raises:
        RuntimeError: If the HEAD request fails.
    """
    try:
        return _get_client().head_object(Bucket=bucket, Key=key)
    except Exception as e:
        raise RuntimeError(f"Failed to HEAD s3://{bucket}/{key}: {e}") from e


def read_bytes(bucket: str, key: str) -> bytes:
    """Read an S3 object and return its body as raw bytes.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        The raw bytes of the object body.

    Raises:
        RuntimeError: If the S3 read fails.
    """
    try:
        obj = _get_client().get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    except Exception as e:
        raise RuntimeError(f"Failed to read bytes from s3://{bucket}/{key}: {e}") from e
