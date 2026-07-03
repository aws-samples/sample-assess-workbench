"""
Resolve Agent ARNs Lambda — Maps agent types from the approved plan to their
AgentCore runtime ARNs via DynamoDB registry + SSM Parameter Store.

Runs after plan approval, before agent execution. This ensures ARNs are
resolved for exactly the agents in the user-approved plan.
"""

import logging
import os

from core.registry import load_agent_arns

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    "required": ["plan"],
    "optional": [],
}


def lambda_handler(event: dict, context) -> dict:
    # Extract unique agent types from the approved plan
    plan = event["plan"]
    agent_types = set()
    for group in plan.get("groups", []):
        for agent in group.get("agents", []):
            agent_types.add(agent.get("agent_type", ""))
    agent_types.discard("")

    # Resolve ARNs
    all_arns = load_agent_arns(role="review")

    # Filter to only the agents in this plan
    resolved = {t: all_arns[t] for t in agent_types if t in all_arns}

    # Warn about any agents in the plan that couldn't be resolved
    missing = agent_types - set(resolved.keys())
    if missing:
        raise ValueError(
            f"Cannot start review — no registered ARNs for agents: {', '.join(sorted(missing))}. "
            f"Check that these agents are deployed and registered in SSM Parameter Store."
        )

    # Return only the resolved ARNs. Context fields are already in workflow
    # variables — no need to echo the entire event back.
    return {"agent_arns": resolved}
