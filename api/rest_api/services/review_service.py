"""Review business logic."""
import logging
import os
import uuid
from typing import Dict, Any, Optional
from ..data_access import DynamoDBDataAccess, S3DataAccess, StepFunctionsDataAccess

from core.plan_validation import validate_plan
from core.registry import load_agent_registry
from core.connections import get_most_recent_connection
from core.report_renderer import render_markdown_report

logger = logging.getLogger(__name__)


class ReviewService:
    """Handles review business logic."""

    def __init__(self, dynamodb: DynamoDBDataAccess, s3: S3DataAccess,
                 stepfunctions: StepFunctionsDataAccess,
                 connections_table=None):
        self.dynamodb = dynamodb
        self.s3 = s3
        self.stepfunctions = stepfunctions
        self.connections_table = connections_table
        self.websocket_endpoint = os.environ.get('WEBSOCKET_API_ENDPOINT', '')

    def verify_project_ownership(self, project_id: str, user_sub: str) -> Dict[str, Any]:
        """Verify the requesting user owns the project.

        Args:
            project_id: Project identifier.
            user_sub: Cognito user sub from JWT.

        Returns:
            Raw project item if the user owns it.

        Raises:
            KeyError: If the project does not exist.
            PermissionError: If the user does not own the project.
        """
        return self.dynamodb.verify_project_ownership(project_id, user_sub)

    def trigger_review(self, project_id: str, user_sub: str = '') -> Optional[Dict[str, Any]]:
        """Trigger document review by starting Step Functions execution.

        Args:
            project_id: Project identifier
            user_sub: Cognito user sub for WebSocket connection lookup

        Returns:
            Review execution details or None if project not found

        Raises:
            ValueError: If document not uploaded yet
        """
        project = self.dynamodb.get_project(project_id)
        if not project:
            return None

        s3_bucket = project['s3_bucket']
        s3_key = project['s3_key']
        files = project.get('files', [])

        # Validate files exist before claiming in_progress
        if not files:
            raise ValueError('No files associated with project. Upload at least one document before triggering review.')

        # Check at least the canonical file exists
        if not self.s3.document_exists(s3_key):
            raise ValueError('Document not uploaded yet. Please upload document to S3 before triggering review.')

        review_id = f"rev_{uuid.uuid4().hex[:8]}"

        # Atomically claim in_progress — rejects if already in_progress
        self.dynamodb.set_project_in_progress(project_id, review_id=review_id)

        # Look up the user's active WebSocket connection for progress events
        logger.info(f"Looking up connection for user_sub: '{user_sub}'")
        connection_id = get_most_recent_connection(self.connections_table, user_sub) if user_sub else ''
        logger.info(f"Connection lookup result: '{connection_id}'")

        try:
            execution = self.stepfunctions.start_review_execution(
                project_id=project_id,
                review_id=review_id,
                s3_bucket=s3_bucket,
                s3_key=s3_key,
                connection_id=connection_id,
                user_sub=user_sub,
                websocket_endpoint=self.websocket_endpoint,
                files=files if files else None,
            )
        except Exception:
            # Rollback: release the in_progress lock so the user can retry
            self.dynamodb.update_project_status(project_id, 'failed')
            raise

        # Persist execution ARN for stale cleanup and abort operations
        self.dynamodb.update_project_status(
            project_id, 'in_progress',
            execution_arn=execution['execution_arn'],
        )

        return {
            'review_id': review_id,
            'project_id': project_id,
            'status': 'in_progress',
            'execution_arn': execution['execution_arn'],
            'started_at': execution['started_at'],
            'message': 'Review started. Poll GET /projects/{id} to check status.'
        }

    def get_review_plan(self, project_id: str, review_id: str) -> Optional[Dict[str, Any]]:
        """Get a stored review plan.

        Args:
            project_id: Project identifier
            review_id: Review identifier (or 'latest' to get the most recent)

        Returns:
            Plan record or None if not found
        """
        if review_id == 'latest':
            return self.dynamodb.get_latest_plan(project_id)
        return self.dynamodb.get_plan(project_id, review_id)

    def get_review_events(self, project_id: str, review_id: str,
                          after: str | None = None) -> Dict[str, Any]:
        """Get persisted progress events for a review.

        Args:
            project_id: Project identifier
            review_id: Review identifier (or 'latest' to resolve from project)
            after: Optional ISO-8601 timestamp cursor. When provided, only
                events at or after this timestamp are returned.

        Returns:
            Dict with review_id and events list
        """
        # Resolve 'latest' from the project's latest_review_id field,
        # which is written atomically when a review starts and persists
        # indefinitely on the project METADATA record (no TTL).
        if review_id == 'latest':
            project = self.dynamodb.get_project(project_id)
            if not project or not project.get('latest_review_id'):
                return {'review_id': None, 'events': []}
            review_id = project['latest_review_id']

        items = self.dynamodb.get_review_events(project_id, review_id, after=after)
        events = [
            {
                'event': item['event_type'],
                'detail': item.get('detail', {}),
                'ts': item['timestamp'],
            }
            for item in items
        ]
        return {'review_id': review_id, 'events': events}

    def approve_review_plan(self, project_id: str, review_id: str,
                            plan_override: Dict = None) -> Dict[str, Any]:
        """Approve a pending review plan, resuming the Step Functions execution.

        Args:
            project_id: Project identifier
            review_id: Review identifier
            plan_override: Optional modified plan from the user

        Returns:
            Approval result

        Raises:
            ValueError: If plan not found or not in pending_approval status
        """
        item = self.dynamodb.get_plan(project_id, review_id)
        if not item:
            raise ValueError('Review plan not found')
        if item.get('status') != 'pending_approval':
            raise ValueError(f"Plan already {item.get('status', 'unknown')}")

        task_token = item['task_token']
        approved_plan = plan_override if plan_override else item['plan']

        # Validate the plan (same validation as the planner Lambda)
        available_agents = set(load_agent_registry().keys())
        approved_plan = validate_plan(approved_plan, available_agents)

        # Persist first — if this fails, we haven't resumed Step Functions yet
        modified = plan_override is not None
        self.dynamodb.update_plan_status(project_id, review_id, 'approved',
                                         approved_plan=approved_plan,
                                         modified=modified)

        # Resume Step Functions (only after persistence succeeds)
        try:
            self.stepfunctions.send_task_success(task_token, approved_plan)
        except Exception as e:
            # Rollback: revert status so the user can retry.
            # Skip rollback for TaskDoesNotExist — the execution already
            # moved past this state, so "approved" is the correct status.
            error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
            if error_code != 'TaskDoesNotExist':
                logger.error(f"send_task_success failed, rolling back plan status: {e}")
                self.dynamodb.update_plan_status(project_id, review_id, 'pending_approval')
            raise

        # Persist plan_approved event so page-refresh replay reconstructs
        # the correct state (customized plan, executing phase).
        # No WebSocket notification is sent for this event — this is
        # intentional. The frontend dispatches plan_approved optimistically
        # after the API call succeeds, and useEventStream deduplicates
        # when the same event arrives from DynamoDB on the next cursor fetch.
        try:
            self.dynamodb.persist_event(
                project_id, review_id, 'plan_approved',
                detail={'plan': approved_plan, 'modified': modified},
            )
        except Exception as e:
            logger.error(
                f"Failed to persist plan_approved event for "
                f"project={project_id} review={review_id}: {e}"
            )

        return {'status': 'approved', 'review_id': review_id}

    def reject_review_plan(self, project_id: str, review_id: str,
                           reason: str = '') -> Dict[str, Any]:
        """Reject a pending review plan, failing the Step Functions execution.

        Args:
            project_id: Project identifier
            review_id: Review identifier
            reason: Optional rejection reason

        Returns:
            Rejection result

        Raises:
            ValueError: If plan not found or not in pending_approval status
        """
        item = self.dynamodb.get_plan(project_id, review_id)
        if not item:
            raise ValueError('Review plan not found')
        if item.get('status') != 'pending_approval':
            raise ValueError(f"Plan already {item.get('status', 'unknown')}")

        task_token = item['task_token']

        # Persist first — if this fails, we haven't touched Step Functions yet
        self.dynamodb.update_plan_status(project_id, review_id, 'rejected')

        # Fail the Step Functions execution (only after persistence succeeds)
        try:
            self.stepfunctions.send_task_failure(
                task_token,
                error='UserRejected',
                cause=reason or 'User rejected the review plan',
            )
        except Exception as e:
            # Rollback: revert status so the user can retry.
            # Skip rollback for TaskDoesNotExist — the execution already
            # moved past this state, so "rejected" is the correct status.
            error_code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
            if error_code != 'TaskDoesNotExist':
                logger.error(f"send_task_failure failed, rolling back plan status: {e}")
                self.dynamodb.update_plan_status(project_id, review_id, 'pending_approval')
            raise

        return {'status': 'rejected', 'review_id': review_id}

    def abort_review(self, project_id: str, review_id: str,
                     reason: str = '') -> Dict[str, Any]:
        """Abort a running review by stopping the Step Functions execution.

        Args:
            project_id: Project identifier
            review_id: Review identifier
            reason: Optional abort reason

        Returns:
            Abort result

        Raises:
            ValueError: If project not found or not in_progress
        """
        project = self.dynamodb.get_project(project_id)
        if not project:
            raise ValueError('Project not found')
        if project.get('status') != 'in_progress':
            raise ValueError(f"Project is not in progress (status: {project.get('status', 'unknown')})")

        # Use persisted execution ARN — all projects created after the
        # execution_arn persistence was added (in trigger_review) have this field.
        execution_arn = project.get('execution_arn')
        if not execution_arn:
            raise ValueError(
                "Project has no execution ARN — cannot abort. "
                "This project may predate execution ARN tracking."
            )

        self.stepfunctions.stop_execution(
            execution_arn,
            cause=reason or 'User aborted the review',
        )

        self.dynamodb.update_project_status(project_id, 'failed')

        return {'status': 'aborted', 'review_id': review_id, 'project_id': project_id}

    def generate_report(self, project_id: str) -> Optional[str]:
        """Generate a markdown report from the latest review's findings.

        Reads the findings payload from S3 (post quality-merge) and renders
        it as a markdown report. Returns None if no review exists.

        Args:
            project_id: Project identifier.

        Returns:
            Markdown report string, or None if no completed review exists.

        Raises:
            RuntimeError: If findings cannot be read from S3.
        """
        project = self.dynamodb.get_project(project_id)
        if not project:
            return None

        review = self.dynamodb.get_latest_review(project_id)
        if not review:
            return None

        findings_payload = review.get('findings', {})
        if not findings_payload:
            return None

        return render_markdown_report(
            reviews=findings_payload.get('reviews', {}),
            summary=findings_payload.get('summary', {}),
            project_name=project.get('name', 'Unknown'),
            created_at=review.get('created_at', ''),
            plan=findings_payload.get('plan'),
            metrics=findings_payload.get('metrics'),
        )
