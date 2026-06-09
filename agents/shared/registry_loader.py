"""Load agent configuration from the DynamoDB agent registry.

Shared by both review_agent.py and chat_agent.py. The registry is the
runtime source of truth — YAML files are the authoring/seeding format.

The agent's AGENT_TYPE environment variable determines which registry
entry to load. Config is read once at module import time and cached
for the lifetime of the container.
"""

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)


def load_config_from_registry(
    agent_type: str, table_name: str
) -> dict[str, Any]:
    """Load agent config from the DynamoDB agent registry.

    Args:
        agent_type: The agent type identifier (e.g., "security", "risk").
        table_name: The DynamoDB table name (projects table).

    Returns:
        The full registry item as a dict, with finding_schema deserialized
        from JSON string to dict if present.

    Raises:
        KeyError: If the agent is not found in the registry.
    """
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION"))
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    response = table.get_item(
        Key={"PK": "AGENT_REGISTRY", "SK": f"AGENT#{agent_type}"}
    )
    item = response.get("Item")
    if not item:
        raise KeyError(
            f"Agent '{agent_type}' not found in registry table '{table_name}'"
        )

    # finding_schema is stored as a JSON string in DynamoDB by the seed
    # script. Deserialize it so consumers get a dict.
    if isinstance(item.get("finding_schema"), str):
        item["finding_schema"] = json.loads(item["finding_schema"])

    # tool_limits is stored as a JSON string in DynamoDB by the seed
    # script. Deserialize it so consumers get a dict.
    if isinstance(item.get("tool_limits"), str):
        item["tool_limits"] = json.loads(item["tool_limits"])

    return item
