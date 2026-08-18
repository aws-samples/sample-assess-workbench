"""Step Functions data access operations."""

import os
import json
from typing import Dict, Any
import boto3


class StepFunctionsDataAccess:
    """Handles Step Functions execution operations."""

    def __init__(self, state_machine_arn: str = None):
        """Initialize Step Functions data access.

        Args:
            state_machine_arn: State machine ARN. If None, reads from environment.
        """
        self.state_machine_arn = state_machine_arn or os.environ.get("STEP_FUNCTIONS_ARN", "")
        self.client = boto3.client("stepfunctions")

    def start_review_execution(
        self,
        project_id: str,
        review_id: str,
        s3_bucket: str,
        s3_key: str,
        connection_id: str = "",
        websocket_endpoint: str = "",
        user_sub: str = "",
        files: list = None,
    ) -> Dict[str, Any]:
        """Start a Step Functions execution for document review.

        Args:
            project_id: Project identifier
            review_id: Review identifier
            s3_bucket: S3 bucket containing the document
            s3_key: S3 key for the document (canonical, first file)
            connection_id: WebSocket connection ID for real-time progress events
            websocket_endpoint: Optional WebSocket management endpoint URL
            user_sub: Cognito user sub for WebSocket connection lookup
            files: Optional list of file manifest dicts with s3_key and filename

        Returns:
            Execution details (ARN, start date)
        """
        execution_name = f"{project_id}-{review_id}"
        execution_input = {
            "project_id": project_id,
            "review_id": review_id,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "connection_id": connection_id or "",
            "user_sub": user_sub or "",
            "websocket_endpoint": websocket_endpoint or "",
            "files": files if files is not None else [],
        }

        response = self.client.start_execution(
            stateMachineArn=self.state_machine_arn,
            name=execution_name,
            input=json.dumps(execution_input),
        )

        return {
            "execution_arn": response["executionArn"],
            "started_at": response["startDate"].isoformat(),
        }

    def send_task_success(self, task_token: str, output: dict) -> None:
        """Resume a paused Step Functions execution with success.

        Args:
            task_token: The callback task token from the WaitForApproval state
            output: The output payload (approved plan)
        """
        self.client.send_task_success(
            taskToken=task_token,
            output=json.dumps(output, default=str),
        )

    def send_task_failure(
        self, task_token: str, error: str = "UserRejected", cause: str = ""
    ) -> None:
        """Fail a paused Step Functions execution.

        Args:
            task_token: The callback task token from the WaitForApproval state
            error: Error code
            cause: Human-readable failure reason
        """
        self.client.send_task_failure(
            taskToken=task_token,
            error=error,
            cause=cause or "User rejected the review plan",
        )

    def stop_execution(self, execution_arn: str, cause: str = "") -> None:
        """Stop a running Step Functions execution.

        Args:
            execution_arn: The execution ARN to stop
            cause: Human-readable reason for stopping
        """
        self.client.stop_execution(
            executionArn=execution_arn,
            cause=cause or "User aborted the review",
        )
