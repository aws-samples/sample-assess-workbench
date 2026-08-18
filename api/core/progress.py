"""WebSocket progress notification helper shared across workflow Lambdas."""

import json
import os
import boto3
import logging
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

# Connections table for user_sub → connection_id lookup
_CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")
_connections_table = None

# Events table — reuses the main projects table (single-table design)
_EVENTS_TABLE = os.environ.get("DYNAMODB_TABLE_NAME", "")
_events_table = None

# Log at import time if tables are not configured — makes misconfigured
# Lambdas diagnosable from CloudWatch without waiting for user reports.
if not _CONNECTIONS_TABLE:
    logger.info(
        "CONNECTIONS_TABLE not configured — WebSocket broadcast disabled, falling back to single connection_id"
    )
if not _EVENTS_TABLE:
    logger.info(
        "DYNAMODB_TABLE_NAME not configured — event persistence disabled, progress events will not be replayed on page refresh"
    )

# Module-level user_sub — set once per Lambda invocation via set_user_sub()
# so callers don't need to pass it on every send_progress() call.
_current_user_sub = ""

# Module-level review context — set once per Lambda invocation via
# set_review_context() so events are persisted to DynamoDB automatically.
_current_project_id = ""
_current_review_id = ""

# Cache resolved connection IDs to avoid repeated full-table scans.
# Keyed by user_sub. Populated on first lookup, reused for the rest of
# the Lambda invocation (and across warm-start invocations for the same user).
_connection_cache = {}


def set_user_sub(user_sub):
    """Set the user_sub for the current Lambda invocation.

    Call this once at the start of lambda_handler. All subsequent
    send_progress() calls will use this user_sub for connection lookup.
    """
    global _current_user_sub
    _current_user_sub = user_sub or ""


def set_review_context(project_id, review_id):
    """Set the project/review context for event persistence.

    Call this once at the start of lambda_handler alongside set_user_sub().
    When set, send_progress() will append each event to DynamoDB for
    replay on page refresh.
    """
    global _current_project_id, _current_review_id
    _current_project_id = project_id or ""
    _current_review_id = review_id or ""


def _get_connections_table():
    """Lazy-init the connections table resource."""
    global _connections_table
    if _connections_table is None and _CONNECTIONS_TABLE:
        _connections_table = boto3.resource("dynamodb").Table(_CONNECTIONS_TABLE)
    return _connections_table


def _get_events_table():
    """Lazy-init the events table resource (same table as projects)."""
    global _events_table
    if _events_table is None and _EVENTS_TABLE:
        _events_table = boto3.resource("dynamodb").Table(_EVENTS_TABLE)
    return _events_table


def _lookup_connections(user_sub):
    """Look up all active connection IDs for a user_sub. Cached per user_sub.

    Only caches non-empty results. When no connections are found (e.g. the
    user hasn't connected yet or reconnected with a new connection ID),
    subsequent calls will re-scan the table so that newly established
    connections are picked up without waiting for a Lambda cold start.
    """
    if user_sub in _connection_cache:
        return _connection_cache[user_sub]

    table = _get_connections_table()
    if not table or not user_sub:
        return []
    try:
        from core.connections import lookup_connections

        connections = lookup_connections(table, user_sub)
        if connections:
            _connection_cache[user_sub] = connections
        return connections
    except Exception as e:
        logger.warning(f"Connection lookup failed for {user_sub}: {e}")
        return []


def _persist_event(event_type, detail, timestamp):
    """Append an event to DynamoDB for replay. Fire-and-forget."""
    if not _current_project_id or not _current_review_id:
        return
    table = _get_events_table()
    if not table:
        return
    try:
        # SK format: EVENT#{review_id}#{timestamp} — gives chronological order
        # within a review when queried with begins_with.
        sk = f"EVENT#{_current_review_id}#{timestamp}"
        # Serialize detail, converting floats to Decimal for DynamoDB
        safe_detail = json.loads(json.dumps(detail or {}), parse_float=Decimal)
        table.put_item(
            Item={
                "PK": f"PROJECT#{_current_project_id}",
                "SK": sk,
                "event_type": event_type,
                "detail": safe_detail,
                "timestamp": timestamp,
                "review_id": _current_review_id,
            }
        )
    except Exception as e:
        # Non-blocking — event persistence must never break the workflow
        logger.warning(f"Event persist failed: {e}")


def send_progress(connection_id, endpoint_url, event_type, detail):
    """Push a review_progress event over WebSocket and persist to DynamoDB.

    When a user_sub has been set via set_user_sub(), broadcasts to all
    active connections for that user. Falls back to the single connection_id
    for backward compatibility. Silently ignores failures.

    When review context has been set via set_review_context(), appends the
    event to DynamoDB for page-refresh replay. This is fire-and-forget.
    """
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    # Persist event to DynamoDB (non-blocking)
    _persist_event(event_type, detail, timestamp)

    if not endpoint_url:
        return

    connection_ids = []
    if _current_user_sub:
        connection_ids = _lookup_connections(_current_user_sub)
    if not connection_ids and connection_id:
        connection_ids = [connection_id]
    if not connection_ids:
        return

    payload = json.dumps(
        {
            "type": "events_available",
        }
    ).encode("utf-8")

    apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)
    for cid in connection_ids:
        try:
            apigw.post_to_connection(ConnectionId=cid, Data=payload)
        except apigw.exceptions.GoneException:
            # Connection is stale — invalidate cache so next call re-scans
            _connection_cache.pop(_current_user_sub, None)
        except Exception:
            pass
