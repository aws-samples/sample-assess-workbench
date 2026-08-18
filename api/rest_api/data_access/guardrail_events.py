"""DynamoDB data access for guardrail intervention events.

Separate table from the main projects table — guardrail events are an
audit/observability concern with different access patterns (time-range
scans across all projects, no relationship to project item collections).

Table schema:
    PK: YEAR#{YYYY}          — partitioned by year to avoid hot partitions
    SK: {ISO-timestamp}#{uuid4-short}  — unique, time-ordered within partition
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key


class GuardrailEventsAccess:
    """Handles DynamoDB operations for the guardrail events audit table."""

    def __init__(self, table_name: str = ""):
        """Initialize guardrail events data access.

        Args:
            table_name: DynamoDB table name. If empty, reads from
                GUARDRAIL_EVENTS_TABLE env var. If that is also empty,
                operations are no-ops (feature not configured).
        """
        self.table_name = table_name or os.environ.get("GUARDRAIL_EVENTS_TABLE", "")
        self._table = None

    @property
    def table(self):
        """Lazy-init the DynamoDB Table resource."""
        if self._table is None and self.table_name:
            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    @property
    def configured(self) -> bool:
        """Whether the guardrail events table is configured."""
        return bool(self.table_name)

    def persist_event(
        self,
        *,
        project_id: str,
        agent_type: str,
        agent_role: str,
        action_taken: str,
        user_sub: str = "",
        user_email: str = "",
        policy_triggered: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist a guardrail intervention event.

        Args:
            project_id: Project the agent was operating on.
            agent_type: Agent type identifier (e.g. 'architecture_chat').
            agent_role: 'chat' or 'review'.
            action_taken: What the guardrail did (e.g. 'intervened', 'blocked').
            user_sub: Cognito user sub (if available from payload).
            user_email: Cognito user email (if available).
            policy_triggered: Which policy triggered (e.g. 'content_filter', 'pii').
            detail: Optional extra detail dict.
        """
        if not self.configured:
            return

        now = datetime.now(tz=timezone.utc)
        timestamp = now.isoformat()
        short_id = uuid.uuid4().hex[:8]

        item: Dict[str, Any] = {
            "PK": f"YEAR#{now.year}",
            "SK": f"{timestamp}#{short_id}",
            "timestamp": timestamp,
            "project_id": project_id,
            "agent_type": agent_type,
            "agent_role": agent_role,
            "action_taken": action_taken,
        }

        if user_sub:
            item["user_sub"] = user_sub
        if user_email:
            item["user_email"] = user_email
        if policy_triggered:
            item["policy_triggered"] = policy_triggered
        if detail:
            item["detail"] = detail

        self.table.put_item(Item=item)

    def query_events(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query guardrail events with optional date range and project filter.

        Scans across year partitions that overlap the requested date range.
        For the expected low volume of guardrail events, this is efficient.

        Args:
            start_date: ISO-8601 date string (inclusive). Defaults to 30 days ago.
            end_date: ISO-8601 date string (inclusive). Defaults to now.
            project_id: Optional project ID filter.
            limit: Maximum events to return.

        Returns:
            List of event items, newest first.
        """
        if not self.configured:
            return []

        now = datetime.now(tz=timezone.utc)

        if not end_date:
            end_dt = now
        else:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

        if not start_date:
            from datetime import timedelta

            start_dt = now - timedelta(days=30)
        else:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))

        # Determine which year partitions to query
        years = list(range(start_dt.year, end_dt.year + 1))

        filter_expr = None

        if project_id:
            filter_expr = Attr("project_id").eq(project_id)

        all_items: List[Dict[str, Any]] = []

        for year in years:
            # SK range within this year partition
            if year == start_dt.year:
                sk_start = start_dt.isoformat()
            else:
                sk_start = f"{year}-01-01T00:00:00+00:00"

            if year == end_dt.year:
                sk_end = end_dt.isoformat() + "\uffff"
            else:
                sk_end = f"{year}-12-31T23:59:59+00:00\uffff"

            query_kwargs: Dict[str, Any] = {
                "KeyConditionExpression": (
                    Key("PK").eq(f"YEAR#{year}") & Key("SK").between(sk_start, sk_end)
                ),
                "ScanIndexForward": False,
                "Limit": limit,
            }

            if filter_expr:
                query_kwargs["FilterExpression"] = filter_expr

            response = self.table.query(**query_kwargs)
            all_items.extend(response.get("Items", []))

            # Paginate within each year partition
            while response.get("LastEvaluatedKey") and len(all_items) < limit:
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                query_kwargs["Limit"] = limit - len(all_items)
                response = self.table.query(**query_kwargs)
                all_items.extend(response.get("Items", []))

            if len(all_items) >= limit:
                break

        # Sort all items by timestamp descending (across year boundaries)
        all_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return all_items[:limit]
