"""Authentication and authorisation utilities for API handlers.

Centralises JWT claim extraction and role resolution so handlers don't
duplicate the same requestContext traversal logic.
"""

import os
from enum import Enum
from functools import wraps
from typing import Dict, Any, Tuple

from rest_api.utils.responses import error_response

# Cognito group names — must match the groups created in Terraform.
ADMIN_GROUP = "admins"
USER_GROUP = "users"
VIEWER_GROUP = "viewers"


class UserRole(Enum):
    """Role assigned to an authenticated user via Cognito group membership."""

    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


def _extract_claims(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract JWT claims from an API Gateway event.

    Args:
        event: API Gateway HTTP API v2 event dict.

    Returns:
        Claims dict (may be empty if authorizer context is absent).
    """
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def get_user_identity(event: Dict[str, Any]) -> Tuple[str, str]:
    """Extract user sub and email from JWT claims.

    Args:
        event: API Gateway event with JWT authorizer context.

    Returns:
        Tuple of (user_sub, user_email). user_email may be empty string
        if not present in the token.

    Raises:
        ValueError: If the user sub is missing from the JWT claims.
    """
    claims = _extract_claims(event)
    user_sub = claims.get("sub", "")
    if not user_sub:
        raise ValueError("Missing user identity in JWT claims")
    return user_sub, claims.get("email", "")


def get_user_role(event: Dict[str, Any]) -> UserRole:
    """Resolve the user's role from Cognito group membership.

    Groups arrive as a space-separated string or a list depending on
    the Cognito / API Gateway configuration.

    Args:
        event: API Gateway event with JWT authorizer context.

    Returns:
        UserRole enum value.

    Raises:
        PermissionError: If the user belongs to no recognised group.
    """
    claims = _extract_claims(event)
    groups = claims.get("cognito:groups", "")

    if isinstance(groups, str):
        # May be a space-separated string or a JSON-array-like string
        # e.g. "[admins users]"
        groups = groups.strip("[]").split()
    elif not isinstance(groups, list):
        groups = []

    if ADMIN_GROUP in groups:
        return UserRole.ADMIN
    if USER_GROUP in groups:
        return UserRole.USER
    if VIEWER_GROUP in groups:
        return UserRole.VIEWER

    # Authenticated users with no recognised group default to viewer (least-privilege).
    # This covers federated users on first login before the Post-Authentication
    # Lambda assigns them to the viewers group on their second authentication.
    return UserRole.VIEWER


def can_read_admin_views(event: Dict[str, Any]) -> bool:
    """Check if the caller may READ admin/privileged views (not write).

    Admin views (agent registry, standards corpus, guardrail events) are
    readable by both admins and viewers. Viewer is a full-read, zero-write
    role: demo stakeholders see everything an admin sees but cannot mutate.

    This is intentionally NOT extended to the USER role. Guardrail events
    expose user emails; surfacing those to arbitrary project-owning users in
    a non-demo deployment would over-share. Viewers are trusted stakeholders
    by definition, so the exposure is acceptable for that role only.

    Writes to these resources remain admin-only (see each handler's _is_admin
    check on the mutating routes).

    Args:
        event: API Gateway event with JWT authorizer context.

    Returns:
        True if the user is an admin or a viewer.
    """
    try:
        return get_user_role(event) in (UserRole.ADMIN, UserRole.VIEWER)
    except PermissionError:
        return False


def is_federated(event: Dict[str, Any]) -> bool:
    """Check if the authenticated user logged in via a federated identity provider.

    Federated users (e.g. via an external OIDC provider) have an 'identities'
    claim in their JWT token. Native Cognito users (email/password) do not.

    Args:
        event: API Gateway event with JWT authorizer context.

    Returns:
        True if the user authenticated via a federated provider.
    """
    claims = _extract_claims(event)
    identities = claims.get("identities", "")
    # identities arrives as a JSON-encoded string in some API GW configs
    if isinstance(identities, str):
        return identities.strip() not in ("", "[]")
    if isinstance(identities, list):
        return len(identities) > 0
    return False


# Environment flag — when FEDERATION_ENABLED is true, federated users are read-only.
_FEDERATION_ENABLED = os.environ.get("FEDERATION_ENABLED", "false").lower() == "true"


def require_write_access(handler):
    """Decorator that rejects mutations from federated (read-only) users.

    When OIDC federation is enabled, federated users get full read access
    but cannot perform mutations. This decorator should wrap any handler that
    creates, updates, or deletes data.

    Handlers that remain open to federated users (reviews, chat) should NOT
    use this decorator.
    """

    @wraps(handler)
    def wrapper(*args):
        # The event is always the second-to-last argument (before context)
        # per the routing convention: handler(*path_params, event, context)
        event = args[-2]
        if _FEDERATION_ENABLED and is_federated(event):
            return error_response(403, "Read-only access. Sign in with email for full access.")
        return handler(*args)

    return wrapper
