"""WebSocket connection lookup by user.

Provides a single implementation for finding active WebSocket connections
for a given user_sub. Used by progress.py and can replace
ConnectionsDataAccess in the REST API.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


def lookup_connections(table, user_sub: str) -> List[str]:
    """Look up all active connection IDs for a user_sub.

    Scans the connections table filtered by userSub. The table is small
    (one row per active WebSocket connection, TTL-cleaned) so a filtered
    scan is acceptable.

    Args:
        table: boto3 DynamoDB Table resource for the connections table.
        user_sub: The Cognito user sub to look up.

    Returns:
        List of connectionId strings. Empty list if none found.

    Raises:
        Exception: Propagates any DynamoDB scan errors.
    """
    if not table or not user_sub:
        return []

    from boto3.dynamodb.conditions import Attr

    response = table.scan(
        FilterExpression=Attr("userSub").eq(user_sub),
        ProjectionExpression="connectionId",
    )
    return [item["connectionId"] for item in response.get("Items", [])]


def get_most_recent_connection(table, user_sub: str) -> str:
    """Return the most recently connected connectionId for a user, or ''.

    Args:
        table: boto3 DynamoDB Table resource for the connections table.
        user_sub: The Cognito user sub to look up.

    Returns:
        The most recent connectionId, or empty string if none found.

    Raises:
        Exception: Propagates any DynamoDB scan errors.
    """
    if not table or not user_sub:
        return ""

    from boto3.dynamodb.conditions import Attr

    response = table.scan(
        FilterExpression=Attr("userSub").eq(user_sub),
        ProjectionExpression="connectionId, connectedAt",
    )
    items = response.get("Items", [])
    if not items:
        return ""

    items.sort(key=lambda x: x.get("connectedAt", ""), reverse=True)
    return items[0]["connectionId"]
