"""Post-authentication Lambda trigger for Cognito.

Assigns a default Cognito group to federated users on first login.
When a user authenticates and has no group membership, this trigger
assigns them to the DEFAULT_GROUP (defaults to 'viewers') following
least-privilege principles.
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

DEFAULT_GROUP = os.environ.get("DEFAULT_GROUP", "viewers")

cognito = boto3.client("cognito-idp")


def handler(event: dict, context) -> dict:
    """Cognito Post-Authentication trigger handler.

    Args:
        event: Cognito trigger event containing userPoolId and userName.
        context: Lambda context (unused).

    Returns:
        The unmodified event (required by Cognito trigger contract).

    Raises:
        ClientError: If Cognito API calls fail (propagates to caller).
    """
    user_pool_id = event["userPoolId"]
    username = event["userName"]

    # Check existing group membership — only recognised role groups count.
    # Cognito auto-creates a provider-scoped group (e.g.
    # "us-west-2_xxxxxxxxx_<ProviderName>") for federated users, but that's
    # not a role assignment.
    ROLE_GROUPS = {"admins", "users", "viewers"}
    response = cognito.admin_list_groups_for_user(
        UserPoolId=user_pool_id,
        Username=username,
    )

    current_groups = [g["GroupName"] for g in response.get("Groups", [])]
    has_role_group = any(g in ROLE_GROUPS for g in current_groups)

    if not has_role_group:
        logger.info('Assigning default group "%s" to user %s', DEFAULT_GROUP, username)
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName=DEFAULT_GROUP,
        )
    else:
        role_groups = [g for g in current_groups if g in ROLE_GROUPS]
        logger.info("User %s already in role groups: %s", username, role_groups)

    return event
