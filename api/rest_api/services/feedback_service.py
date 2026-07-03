"""Feedback business logic."""

from typing import Dict, Any
from ..data_access import DynamoDBDataAccess


class FeedbackService:
    """Handles user feedback on findings."""

    def __init__(self, dynamodb: DynamoDBDataAccess):
        self.dynamodb = dynamodb

    def submit_feedback(
        self, project_id: str, finding_id: str, agent_type: str, value: str, user: str
    ) -> Dict[str, Any]:
        """Submit or update feedback for a finding.

        Args:
            project_id: Project identifier
            finding_id: Finding ID (e.g. ARCH-001)
            agent_type: Agent type
            value: 'up' or 'down'
            user: User email

        Returns:
            Feedback record
        """
        item = self.dynamodb.put_feedback(project_id, agent_type, finding_id, value, user)
        return {
            "finding_id": item["finding_id"],
            "agent_type": item["agent_type"],
            "value": item["value"],
            "timestamp": item["timestamp"],
        }

    def get_project_feedback(self, project_id: str) -> Dict[str, Any]:
        """Get all feedback for a project, grouped by finding.

        Args:
            project_id: Project identifier

        Returns:
            Dict with feedback list and counts
        """
        items = self.dynamodb.get_feedback(project_id)
        feedback = [
            {
                "finding_id": it["finding_id"],
                "agent_type": it["agent_type"],
                "value": it["value"],
                "user": it["user"],
                "timestamp": it["timestamp"],
            }
            for it in items
        ]
        return {"feedback": feedback, "count": len(feedback)}
