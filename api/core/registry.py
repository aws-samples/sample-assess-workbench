"""Agent registry queries, caching, and ARN resolution.

This module is the single source of truth for reading agent registry data
from DynamoDB. It lives in the ``core`` layer so that both workflow Lambdas
and the REST API Lambda can use it.

Workflow Lambdas use the cached, high-level helpers (``load_agent_registry``,
``load_agent_arns``). The REST API's ``DynamoDBDataAccess`` class delegates
its registry read methods here to avoid duplicating query/filter logic.

Write operations (create, update) live in ``DynamoDBDataAccess`` since only
the API Lambda mutates registry data.
"""

import os
import time
import boto3
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# TTL for all caches (seconds). Registry changes propagate within this window.
CACHE_TTL = 60

# Module-level caches with timestamps
_agent_registry_cache: Optional[Dict[str, Dict]] = None
_agent_registry_cache_time: float = 0
_agent_arns_cache: Dict[str, Dict[str, str]] = {}
_agent_arns_cache_time: Dict[str, float] = {}


def _is_fresh(cache_time: float) -> bool:
    """Check if a cache entry is still within TTL."""
    return (time.time() - cache_time) < CACHE_TTL


def _resolve_table_name(table_name: Optional[str] = None) -> str:
    """Resolve DynamoDB table name from argument or environment.

    Args:
        table_name: Explicit table name, or None to read from env.

    Returns:
        Resolved table name.

    Raises:
        RuntimeError: If no table name can be determined.
    """
    resolved = (
        table_name
        or os.environ.get('PROJECTS_TABLE')
        or os.environ.get('DYNAMODB_TABLE_NAME', '')
    )
    if not resolved:
        raise RuntimeError(
            'Agent registry unavailable: no DynamoDB table name configured. '
            'Set PROJECTS_TABLE or DYNAMODB_TABLE_NAME environment variable.'
        )
    return resolved


# ---------------------------------------------------------------------------
# Core query — single source of truth for registry reads
# ---------------------------------------------------------------------------


def query_agent_registry(
    table,
    *,
    enabled_only: bool = True,
    has_review_agent: Optional[bool] = None,
    has_chat_agent: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Query agent registry items from DynamoDB with parameterized filtering.

    This is the foundational read function. All other registry read helpers
    (``load_agent_registry``, ``DynamoDBDataAccess.get_agent_registry``, etc.)
    delegate here so filtering logic is defined once.

    Args:
        table: boto3 DynamoDB Table resource.
        enabled_only: If True, exclude agents where ``enabled`` is False.
        has_review_agent: If not None, filter to agents where
            ``has_review_agent`` matches this value.
        has_chat_agent: If not None, filter to agents where
            ``has_chat_agent`` matches this value.

    Returns:
        List of matching agent registry items (unsorted — callers sort as
        needed for their use case).

    Raises:
        RuntimeError: If the DynamoDB query fails.
    """
    try:
        response = table.query(
            KeyConditionExpression='PK = :pk',
            ExpressionAttributeValues={':pk': 'AGENT_REGISTRY'},
        )
    except Exception as e:
        raise RuntimeError(
            f'Failed to query agent registry from DynamoDB: {e}'
        ) from e

    items = response.get('Items', [])

    if enabled_only:
        items = [i for i in items if i.get('enabled', True)]
    if has_review_agent is not None:
        items = [i for i in items if i.get('has_review_agent', False) is has_review_agent]
    if has_chat_agent is not None:
        items = [i for i in items if i.get('has_chat_agent', False) is has_chat_agent]

    return items


def get_agent_registry_entry(table, agent_type: str) -> Optional[Dict[str, Any]]:
    """Get a single agent registry entry by type.

    Args:
        table: boto3 DynamoDB Table resource.
        agent_type: Agent type identifier (e.g. 'risk', 'security').

    Returns:
        Agent registry item, or None if not found.

    Raises:
        RuntimeError: If the DynamoDB read fails.
    """
    try:
        response = table.get_item(
            Key={'PK': 'AGENT_REGISTRY', 'SK': f'AGENT#{agent_type}'}
        )
    except Exception as e:
        raise RuntimeError(
            f'Failed to read agent registry entry "{agent_type}": {e}'
        ) from e

    return response.get('Item')


# ---------------------------------------------------------------------------
# Cached helpers for workflow Lambdas
# ---------------------------------------------------------------------------


def load_agent_registry(table_name: str = None) -> Dict[str, Dict]:
    """Load enabled review agents from DynamoDB registry. Cached with TTL.

    Returns a dict keyed by ``agent_type`` for fast lookup by callers like
    ``plan_review`` and ``run_benchmark``.

    Args:
        table_name: DynamoDB table name. Defaults to PROJECTS_TABLE or
                    DYNAMODB_TABLE_NAME env var.

    Returns:
        Dict mapping agent_type to registry item dict.

    Raises:
        RuntimeError: If the registry cannot be loaded (missing table name,
                      DynamoDB error, or empty registry).
    """
    global _agent_registry_cache, _agent_registry_cache_time
    if _agent_registry_cache is not None and _is_fresh(_agent_registry_cache_time):
        return _agent_registry_cache

    resolved_name = _resolve_table_name(table_name)

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(resolved_name)

    items = query_agent_registry(table, enabled_only=True, has_review_agent=True)

    registry = {item['agent_type']: item for item in items}
    if not registry:
        raise RuntimeError(
            'Agent registry is empty: no enabled review agents found in DynamoDB. '
            'Run "task deploy:seed" to populate the registry.'
        )

    logger.info(f'Loaded {len(registry)} agents from registry: {list(registry.keys())}')
    _agent_registry_cache = registry
    _agent_registry_cache_time = time.time()
    return registry


def load_agent_arns(
    table_name: str = None,
    project_name: str = None,
    environment: str = None,
    role: str = 'review',
) -> Dict[str, str]:
    """Resolve agent ARNs from DynamoDB registry + SSM. Cached with TTL.

    Args:
        table_name: DynamoDB table name.
        project_name: SSM parameter prefix project name.
        environment: SSM parameter prefix environment.
        role: ``'review'`` or ``'chat'`` — determines which registry flag
            and SSM param field to use.

    Returns:
        Dict mapping agent_type to resolved ARN string.

    Raises:
        RuntimeError: If the registry or SSM cannot be queried.
    """
    global _agent_arns_cache, _agent_arns_cache_time
    if role in _agent_arns_cache and _is_fresh(_agent_arns_cache_time.get(role, 0)):
        return _agent_arns_cache[role]

    resolved_name = _resolve_table_name(table_name)
    project_name = project_name or os.environ.get('PROJECT_NAME', 'risk-assessor')
    environment = environment or os.environ.get('ENVIRONMENT', 'dev')

    has_field = 'has_review_agent' if role == 'review' else 'has_chat_agent'
    ssm_field = 'review_agent_ssm_param' if role == 'review' else 'chat_agent_ssm_param'

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(resolved_name)

    # 1. Query registry with the appropriate capability filter
    filter_kwargs = {has_field: True}
    items = query_agent_registry(table, enabled_only=True, **filter_kwargs)
    registry = {item['agent_type']: item for item in items}

    # 2. Batch-read all agent ARNs from SSM
    try:
        ssm = boto3.client('ssm')
        ssm_prefix = f'/{project_name}/{environment}/agent/'
        ssm_params: Dict[str, str] = {}
        paginator = ssm.get_paginator('get_parameters_by_path')
        for page in paginator.paginate(Path=ssm_prefix, Recursive=False):
            for param in page['Parameters']:
                ssm_params[param['Name']] = param['Value']
    except Exception as e:
        raise RuntimeError(
            f'Failed to read SSM parameters under {ssm_prefix}: {e}'
        ) from e

    # 3. Match registry entries to SSM values
    resolved: Dict[str, str] = {}
    for agent_type, item in registry.items():
        ssm_param = item.get(ssm_field, '')
        if ssm_param and ssm_param in ssm_params:
            resolved[agent_type] = ssm_params[ssm_param]

    logger.info(f'Resolved {len(resolved)} {role} agent ARNs: {list(resolved.keys())}')

    if resolved:
        _agent_arns_cache[role] = resolved
        _agent_arns_cache_time[role] = time.time()
    return resolved
