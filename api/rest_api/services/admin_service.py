"""Admin business logic — agent registry management and reference data."""

import logging
from typing import Dict, Any, Optional
from ..data_access import DynamoDBDataAccess, GuardrailEventsAccess

logger = logging.getLogger(__name__)

# Fields to exclude from the public GET /agents response
_AGENT_INTERNAL_FIELDS = {
    "PK",
    "SK",
    "review_agent_ssm_param",
    "chat_agent_ssm_param",
    "judge_agent_ssm_param",
    "created_at",
}


class AdminService:
    """Handles admin operations on the agent registry and reference data."""

    def __init__(
        self, dynamodb: DynamoDBDataAccess, guardrail_events: Optional[GuardrailEventsAccess] = None
    ):
        self.dynamodb = dynamodb
        self.guardrail_events = guardrail_events

    def list_registry(self) -> Dict[str, Any]:
        """List review agent registry entries with full config (including disabled).

        Chat agents are not returned as top-level entries. Instead, each
        review agent's linked chat agent data is attached as a nested
        ``chat_agent_config`` dict so the admin UI can display it inline.

        Returns:
            Dict with agents list (review agents only, chat data nested).
        """
        items = self.dynamodb.get_full_agent_registry()

        # Separate review agents from chat agents
        chat_agents: Dict[str, Dict[str, Any]] = {}
        review_agents: list[Dict[str, Any]] = []
        for item in items:
            entry = {k: v for k, v in item.items() if k not in ("PK", "SK")}
            if entry.get("role") == "chat":
                chat_agents[entry["agent_type"]] = entry
            else:
                review_agents.append(entry)

        # Attach each review agent's linked chat agent config
        for agent in review_agents:
            chat_name = agent.get("chat_agent", "")
            if chat_name and chat_name in chat_agents:
                agent["chat_agent_config"] = chat_agents[chat_name]

        review_agents.sort(key=lambda a: int(a.get("sort_order", 99)))
        return {"agents": review_agents}

    def update_registry(self, agent_type: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an agent's registry configuration.

        Args:
            agent_type: Agent type identifier
            updates: Fields to update (display_name, icon, sort_order,
                     finding_schema, judge_defaults, default_depth, enabled)

        Returns:
            Updated agent entry

        Raises:
            ValueError: If agent not found or invalid fields
        """
        # Validate agent exists
        existing = self.dynamodb.get_agent_registry_entry(agent_type)
        if not existing:
            raise ValueError(f"Agent not found: {agent_type}")

        # Whitelist of editable fields
        allowed = {
            "display_name",
            "icon",
            "color",
            "description",
            "sort_order",
            "finding_schema",
            "judge_defaults",
            "coach_guidance",
            "default_depth",
            "enabled",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            raise ValueError("No valid fields to update")

        self.dynamodb.update_agent_registry(agent_type, filtered)

        # Return the updated entry
        updated = self.dynamodb.get_agent_registry_entry(agent_type)
        return {k: v for k, v in updated.items() if k not in ("PK", "SK")}

    def list_agents(self) -> Dict[str, Any]:
        """List enabled review agents for frontend consumption (public endpoint).

        Chat agents are excluded — they're an internal concept used by the
        WebSocket chat handler, not something the frontend renders in its
        agent list. The frontend uses display_name, icon, and color fields
        which only review agents have.

        Filters out internal fields like SSM param names.

        Returns:
            Dict with agents list.
        """
        registry = self.dynamodb.get_agent_registry(has_review_agent=True)
        agents = [
            {k: v for k, v in item.items() if k not in _AGENT_INTERNAL_FIELDS} for item in registry
        ]
        return {"agents": agents}

    def get_guardrail_events(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List guardrail intervention events for the admin dashboard.

        Args:
            start_date: ISO-8601 date string (inclusive lower bound).
            end_date: ISO-8601 date string (inclusive upper bound).
            project_id: Optional project ID filter.
            limit: Maximum events to return.

        Returns:
            Dict with events list and count.
        """
        if not self.guardrail_events or not self.guardrail_events.configured:
            return {"events": [], "count": 0, "configured": False}

        events = self.guardrail_events.query_events(
            start_date=start_date,
            end_date=end_date,
            project_id=project_id,
            limit=limit,
        )

        # Strip DynamoDB key attributes from response
        cleaned = [{k: v for k, v in event.items() if k not in ("PK", "SK")} for event in events]

        return {"events": cleaned, "count": len(cleaned), "configured": True}
