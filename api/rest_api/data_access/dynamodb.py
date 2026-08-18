"""DynamoDB data access operations."""

import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import boto3
from boto3.dynamodb.conditions import Key

from rest_api.utils.parsers import deserialize_review
from core.dynamodb import convert_floats_to_decimal
from core.s3 import read_json as s3_read_json


class ConflictError(Exception):
    """Raised when an operation conflicts with the current resource state."""

    pass


class DynamoDBDataAccess:
    """Handles all DynamoDB operations for projects, reviews, and chat."""

    def __init__(self, table_name: str = None):
        """Initialize DynamoDB data access.

        Args:
            table_name: DynamoDB table name. If None, reads from environment.
        """
        self.table_name = table_name or os.environ["DYNAMODB_TABLE_NAME"]
        dynamodb = boto3.resource("dynamodb")
        self.table = dynamodb.Table(self.table_name)

    # Project operations

    def create_project(
        self,
        project_id: str,
        name: str,
        description: str,
        s3_bucket: str,
        s3_key: str,
        created_by: str = "",
        created_by_email: str = "",
        context_id: str = "",
        files: list = None,
    ) -> Dict[str, Any]:
        """Create a new project in DynamoDB.

        Args:
            project_id: Unique project identifier
            name: Project name
            description: Project description
            s3_bucket: S3 bucket name for document
            s3_key: S3 key for document (canonical, first file)
            created_by: Cognito user sub
            created_by_email: Cognito user email
            context_id: Optional organizational context ID
            files: Optional list of file manifest dicts with s3_key and filename

        Returns:
            Created project item
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        # GSI2 partitions projects by owner for efficient per-user queries.
        # Projects with no owner (created before ownership tracking) use
        # USER#unknown so they remain queryable by admins via backfill.
        gsi2_pk = f"USER#{created_by}" if created_by else "USER#unknown"

        item = {
            "PK": f"PROJECT#{project_id}",
            "SK": "METADATA",
            "GSI1PK": "PROJECT",
            "GSI1SK": timestamp,
            "GSI2PK": gsi2_pk,
            "GSI2SK": timestamp,
            "project_id": project_id,
            "name": name,
            "description": description,
            "status": "pending",
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "created_at": timestamp,
            "updated_at": timestamp,
            "created_by": created_by,
            "created_by_email": created_by_email,
            "context_id": context_id,
        }

        if files:
            item["files"] = files

        self.table.put_item(Item=item)
        return item

    def delete_project(self, project_id: str) -> int:
        """Delete a project and all related items (reviews, chat messages).

        Args:
            project_id: Project identifier

        Returns:
            Number of items deleted
        """
        # Query all items for this project
        response = self.table.query(KeyConditionExpression=Key("PK").eq(f"PROJECT#{project_id}"))
        items = response.get("Items", [])

        # Handle pagination
        while response.get("LastEvaluatedKey"):
            response = self.table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project_id}"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        # Batch delete all items
        with self.table.batch_writer() as batch:
            for item in items:
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})

        return len(items)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get project metadata by ID.

        Args:
            project_id: Project identifier

        Returns:
            Project item or None if not found
        """
        response = self.table.get_item(Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"})
        return response.get("Item")

    def list_projects(self, status_filter: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List all projects, optionally filtered by status.

        Args:
            status_filter: Optional status to filter by
            limit: Maximum number of projects to return

        Returns:
            List of project items
        """
        query_params = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq("PROJECT"),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if status_filter:
            from boto3.dynamodb.conditions import Attr

            query_params["FilterExpression"] = Attr("status").eq(status_filter)

        response = self.table.query(**query_params)
        return response.get("Items", [])

    def list_projects_for_user(self, user_sub: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List projects owned by a specific user via GSI2.

        Uses a native key condition on GSI2 (no FilterExpression) so only
        the requesting user's projects are read from DynamoDB.

        Args:
            user_sub: Cognito user sub to filter by.
            limit: Maximum number of projects to return.

        Returns:
            List of project items sorted by creation time descending.
        """
        response = self.table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"USER#{user_sub}"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return response.get("Items", [])

    def verify_project_ownership(self, project_id: str, user_sub: str) -> Dict[str, Any]:
        """Fetch a project and verify the requesting user owns it.

        Args:
            project_id: Project identifier.
            user_sub: Cognito user sub from JWT.

        Returns:
            Project item if the user owns it.

        Raises:
            KeyError: If the project does not exist.
            PermissionError: If the user does not own the project.
        """
        project = self.get_project(project_id)
        if not project:
            raise KeyError(f"Project not found: {project_id}")
        if project.get("created_by") != user_sub:
            raise PermissionError(f"Access denied to project {project_id}")
        return project

    def update_project_status(
        self, project_id: str, status: str, execution_arn: str = None
    ) -> None:
        """Update project status.

        Args:
            project_id: Project identifier
            status: New status (pending, in_progress, completed, failed)
            execution_arn: Optional Step Functions execution ARN to persist
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        update_expr = "SET #status = :status, updated_at = :updated_at"
        attr_names = {"#status": "status"}
        attr_values = {":status": status, ":updated_at": timestamp}

        if execution_arn:
            update_expr += ", execution_arn = :arn"
            attr_values[":arn"] = execution_arn

        self.table.update_item(
            Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

    def set_project_in_progress(
        self, project_id: str, execution_arn: str = None, review_id: str = None
    ) -> None:
        """Atomically set project status to in_progress.

        Uses a conditional write to reject the update if the project is
        already in_progress, preventing concurrent review executions.

        Args:
            project_id: Project identifier
            execution_arn: Optional Step Functions execution ARN to persist
            review_id: Optional review ID to persist as latest_review_id

        Raises:
            ConflictError: If the project is already in_progress
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        update_expr = "SET #status = :in_progress, updated_at = :updated_at"
        attr_names = {"#status": "status"}
        attr_values = {
            ":in_progress": "in_progress",
            ":updated_at": timestamp,
        }

        if execution_arn:
            update_expr += ", execution_arn = :arn"
            attr_values[":arn"] = execution_arn

        if review_id:
            update_expr += ", latest_review_id = :rid"
            attr_values[":rid"] = review_id

        try:
            self.table.update_item(
                Key={"PK": f"PROJECT#{project_id}", "SK": "METADATA"},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=attr_names,
                ExpressionAttributeValues=attr_values,
                ConditionExpression="#status <> :in_progress",
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ConflictError(
                "A review is already in progress for this project. "
                "Wait for it to complete or abort it before starting a new one."
            )

    # Review operations

    def create_review(
        self,
        project_id: str,
        review_id: str,
        findings_s3_bucket: str,
        findings_s3_key: str,
        duration_ms: int = None,
    ) -> Dict[str, Any]:
        """Store review results in DynamoDB.

        Stores an S3 reference to the findings JSON rather than the
        findings blob itself, avoiding the 400KB item size limit.

        Args:
            project_id: Project identifier
            review_id: Review identifier
            findings_s3_bucket: S3 bucket containing findings JSON
            findings_s3_key: S3 key for findings JSON
            duration_ms: Review duration in milliseconds

        Returns:
            Created review item
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        item = {
            "PK": f"PROJECT#{project_id}",
            "SK": f"REVIEW#{timestamp}",
            "review_id": review_id,
            "status": "completed",
            "findings_s3_bucket": findings_s3_bucket,
            "findings_s3_key": findings_s3_key,
            "created_at": timestamp,
        }

        if duration_ms is not None:
            item["duration_ms"] = duration_ms

        self.table.put_item(Item=item)
        return item

    def get_latest_review(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest review for a project.

        Hydrates findings from S3 if the review has an S3 reference,
        then normalizes the item via ``deserialize_review``.

        Args:
            project_id: Project identifier.

        Returns:
            Latest review item with findings hydrated, or None if no reviews exist.

        Raises:
            RuntimeError: If findings cannot be read from S3.
        """
        response = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"PROJECT#{project_id}")
            & Key("SK").begins_with("REVIEW#"),
            ScanIndexForward=False,
            Limit=1,
        )

        items = response.get("Items", [])
        if not items:
            return None

        item = items[0]
        s3_bucket = item.get("findings_s3_bucket", "")
        s3_key = item.get("findings_s3_key", "")
        if s3_bucket and s3_key:
            item["findings"] = s3_read_json(s3_bucket, s3_key)

        return deserialize_review(item)

    # Context document operations

    def create_context(
        self,
        context_id: str,
        name: str,
        description: str,
        s3_bucket: str,
        s3_key: str,
        created_by: str = "",
    ) -> Dict[str, Any]:
        """Create a new organizational context document.

        Args:
            context_id: Unique context identifier
            name: Context document name
            description: Brief description
            s3_bucket: S3 bucket name
            s3_key: S3 key for the document
            created_by: User ID who created it

        Returns:
            Created context item
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()

        item = {
            "PK": f"CONTEXT#{context_id}",
            "SK": "METADATA",
            "GSI1PK": "CONTEXT",
            "GSI1SK": timestamp,
            "context_id": context_id,
            "name": name,
            "description": description,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "created_by": created_by,
            "created_at": timestamp,
        }

        self.table.put_item(Item=item)
        return item

    def get_context(self, context_id: str) -> Optional[Dict[str, Any]]:
        """Get context document metadata by ID."""
        response = self.table.get_item(Key={"PK": f"CONTEXT#{context_id}", "SK": "METADATA"})
        return response.get("Item")

    def list_contexts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List all context documents."""
        response = self.table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq("CONTEXT"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return response.get("Items", [])

    def delete_context(self, context_id: str) -> bool:
        """Delete a context document metadata."""
        self.table.delete_item(Key={"PK": f"CONTEXT#{context_id}", "SK": "METADATA"})
        return True

    # --- Review Plan methods ---

    def get_plan(self, project_id: str, review_id: str) -> Optional[Dict[str, Any]]:
        """Get a review plan by project and review ID."""
        response = self.table.get_item(
            Key={"PK": f"PROJECT#{project_id}", "SK": f"PLAN#{review_id}"}
        )
        return response.get("Item")

    def get_latest_plan(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent review plan for a project."""
        response = self.table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"PROJECT#{project_id}",
                ":prefix": "PLAN#",
            },
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None

    def update_plan_status(
        self,
        project_id: str,
        review_id: str,
        status: str,
        approved_plan: Dict = None,
        modified: bool = False,
    ) -> None:
        """Update a review plan's status."""
        update_expr = "SET #s = :s"
        attr_names = {"#s": "status"}
        attr_values = {":s": status}

        if status == "approved":
            update_expr += ", approved_at = :t, modified = :m"
            attr_values[":t"] = datetime.now(tz=timezone.utc).isoformat()
            attr_values[":m"] = modified
            if approved_plan:
                update_expr += ", approved_plan = :p"
                attr_values[":p"] = convert_floats_to_decimal(approved_plan)

        self.table.update_item(
            Key={"PK": f"PROJECT#{project_id}", "SK": f"PLAN#{review_id}"},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=attr_names,
            ExpressionAttributeValues=attr_values,
        )

    # Agent registry operations

    def get_review_events(
        self, project_id: str, review_id: str, after: str | None = None
    ) -> List[Dict[str, Any]]:
        """Get persisted progress events for a review.

        Events are stored by send_progress() during workflow execution
        with SK format EVENT#{review_id}#{timestamp}.

        Uses a ``between`` range on the sort key so that an optional cursor
        (``after``) can be applied without changing the query structure.
        When ``after`` is None the lower bound sits before any timestamp,
        returning all events (same behaviour as before).  When ``after`` is
        an ISO timestamp the lower bound is inclusive — the frontend
        deduplicates by timestamp so returning the boundary event is harmless
        and keeps this code branch-free.

        Args:
            project_id: Project identifier
            review_id: Review identifier
            after: Optional ISO-8601 timestamp cursor. Only events with a
                sort key greater than or equal to ``EVENT#{review_id}#{after}``
                are returned.

        Returns:
            List of event items in chronological order
        """
        lower = f"EVENT#{review_id}#{after}" if after else f"EVENT#{review_id}#"
        upper = f"EVENT#{review_id}#\uffff"

        key_condition = Key("PK").eq(f"PROJECT#{project_id}") & Key("SK").between(lower, upper)

        response = self.table.query(
            KeyConditionExpression=key_condition,
            ScanIndexForward=True,
        )
        items = response.get("Items", [])

        # Handle pagination for reviews with many events
        while response.get("LastEvaluatedKey"):
            response = self.table.query(
                KeyConditionExpression=key_condition,
                ScanIndexForward=True,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return items

    def persist_event(
        self, project_id: str, review_id: str, event_type: str, detail: Dict = None
    ) -> None:
        """Persist a progress event for page-refresh replay.

        Mirrors the event format written by send_progress() in workflow
        Lambdas so that get_review_events() returns a unified stream.
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        self.table.put_item(
            Item={
                "PK": f"PROJECT#{project_id}",
                "SK": f"EVENT#{review_id}#{timestamp}",
                "event_type": event_type,
                "detail": convert_floats_to_decimal(detail or {}),
                "timestamp": timestamp,
                "review_id": review_id,
            }
        )

    # Feedback operations

    def put_feedback(
        self, project_id: str, agent_type: str, finding_id: str, value: str, user: str
    ) -> Dict[str, Any]:
        """Store or update user feedback on a finding.

        Args:
            project_id: Project identifier
            agent_type: Agent type (architecture, security, risk, etc.)
            finding_id: Finding identifier (e.g. ARCH-001)
            value: Feedback value ('up' or 'down')
            user: User email

        Returns:
            Created/updated feedback item
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds")
        item = {
            "PK": f"PROJECT#{project_id}",
            "SK": f"FEEDBACK#{agent_type}#{finding_id}#{user}",
            "finding_id": finding_id,
            "agent_type": agent_type,
            "value": value,
            "user": user,
            "timestamp": timestamp,
        }
        self.table.put_item(Item=item)
        return item

    def get_feedback(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all feedback for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of feedback items
        """
        response = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"PROJECT#{project_id}")
            & Key("SK").begins_with("FEEDBACK#"),
        )
        return response.get("Items", [])

    def get_agent_registry(
        self,
        *,
        enabled_only: bool = True,
        has_review_agent: Optional[bool] = None,
        has_chat_agent: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Get agents from the registry with optional filtering.

        Delegates to ``core.registry.query_agent_registry`` for the actual
        query and filtering, then sorts by ``sort_order``.

        Args:
            enabled_only: If True (default), exclude disabled agents.
            has_review_agent: If set, filter on the ``has_review_agent`` flag.
            has_chat_agent: If set, filter on the ``has_chat_agent`` flag.

        Returns:
            List of agent registry items, sorted by sort_order.

        Raises:
            RuntimeError: If the DynamoDB query fails.
        """
        from core.registry import query_agent_registry

        items = query_agent_registry(
            self.table,
            enabled_only=enabled_only,
            has_review_agent=has_review_agent,
            has_chat_agent=has_chat_agent,
        )
        items.sort(key=lambda x: int(x.get("sort_order", 99)))
        return items

    def get_full_agent_registry(self) -> List[Dict[str, Any]]:
        """Get ALL agents from the registry (including disabled). For admin use.

        Returns:
            List of all agent registry items.

        Raises:
            RuntimeError: If the DynamoDB query fails.
        """
        from core.registry import query_agent_registry

        return query_agent_registry(self.table, enabled_only=False)

    def get_agent_registry_entry(self, agent_type: str) -> Optional[Dict[str, Any]]:
        """Get a single agent registry entry.

        Args:
            agent_type: Agent type identifier.

        Returns:
            Agent registry item or None if not found.

        Raises:
            RuntimeError: If the DynamoDB read fails.
        """
        from core.registry import get_agent_registry_entry

        return get_agent_registry_entry(self.table, agent_type)

    def create_agent_registry_entry(
        self, agent_type: str, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a new agent registry entry.

        Writes a new item to the AGENT_REGISTRY partition. Fails if an entry
        for the given ``agent_type`` already exists.

        Args:
            agent_type: Unique agent type identifier (e.g. 'risk', 'security').
            fields: All agent configuration fields. Callers are responsible
                for providing the complete set of required fields — this
                method does not inject defaults.

        Returns:
            The created registry item.

        Raises:
            ConflictError: If an agent with this type already exists.
        """
        from datetime import datetime, timezone

        item = {
            "PK": "AGENT_REGISTRY",
            "SK": f"AGENT#{agent_type}",
            "agent_type": agent_type,
            **fields,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        try:
            self.table.put_item(
                Item=convert_floats_to_decimal(item),
                ConditionExpression="attribute_not_exists(PK)",
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ConflictError(
                f'Agent registry entry already exists for type "{agent_type}". '
                f"Use update_agent_registry() to modify an existing entry."
            )

        return item

    def update_agent_registry(self, agent_type: str, updates: Dict[str, Any]) -> None:
        """Update fields on an existing agent registry entry.

        Uses a conditional write to ensure the entry exists before updating.

        Args:
            agent_type: Agent type identifier.
            updates: Dict of field names to new values.

        Raises:
            ValueError: If the agent entry does not exist.
        """
        expr_parts = []
        attr_names = {}
        attr_values = {}

        for i, (key, value) in enumerate(updates.items()):
            placeholder = f"#k{i}"
            val_placeholder = f":v{i}"
            expr_parts.append(f"{placeholder} = {val_placeholder}")
            attr_names[placeholder] = key
            attr_values[val_placeholder] = value

        try:
            self.table.update_item(
                Key={"PK": "AGENT_REGISTRY", "SK": f"AGENT#{agent_type}"},
                UpdateExpression="SET " + ", ".join(expr_parts),
                ExpressionAttributeNames=attr_names,
                ExpressionAttributeValues=attr_values,
                ConditionExpression="attribute_exists(PK)",
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValueError(
                f'Agent registry entry not found for type "{agent_type}". '
                f"Cannot update a non-existent entry."
            )
