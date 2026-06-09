"""Unit tests for rest_api.utils.auth — JWT claim extraction and role resolution."""
import pytest
from rest_api.utils.auth import (
    UserRole,
    get_user_identity,
    get_user_role,
    can_read_admin_views,
    ADMIN_GROUP,
    USER_GROUP,
    VIEWER_GROUP,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_event(sub: str = 'user-123', email: str = 'user@example.com',
                groups=None) -> dict:
    """Build a minimal API Gateway event with JWT authorizer context."""
    claims: dict = {}
    if sub:
        claims['sub'] = sub
    if email:
        claims['email'] = email
    if groups is not None:
        claims['cognito:groups'] = groups

    return {
        'requestContext': {
            'authorizer': {
                'jwt': {
                    'claims': claims,
                }
            }
        }
    }


# ── UserRole enum contract ───────────────────────────────────────────────────

class TestUserRoleEnum:
    """The enum values are referenced by string in the design doc, analytics
    filters, and potentially frontend code. Lock them down so silent drift
    doesn't break callers that compare against the string value."""

    def test_admin_value_is_admin_string(self):
        assert UserRole.ADMIN.value == 'admin'

    def test_user_value_is_user_string(self):
        assert UserRole.USER.value == 'user'

    def test_viewer_value_is_viewer_string(self):
        assert UserRole.VIEWER.value == 'viewer'


# ── get_user_identity ─────────────────────────────────────────────────────────

class TestGetUserIdentity:
    def test_returns_sub_and_email(self):
        event = _make_event(sub='abc-123', email='alice@example.com')
        sub, email = get_user_identity(event)
        assert sub == 'abc-123'
        assert email == 'alice@example.com'

    def test_email_defaults_to_empty_string_when_absent(self):
        event = _make_event(sub='abc-123')
        # Ensure email key is absent from claims
        event['requestContext']['authorizer']['jwt']['claims'].pop('email', None)
        sub, email = get_user_identity(event)
        assert sub == 'abc-123'
        assert email == ''

    def test_raises_value_error_when_sub_missing(self):
        # Callers rely on ValueError specifically to return 401.
        event = _make_event(sub='', email='user@example.com')
        with pytest.raises(ValueError, match='Missing user identity'):
            get_user_identity(event)

    def test_raises_value_error_when_event_empty(self):
        # Full defensive chain: no requestContext, no authorizer, no claims.
        with pytest.raises(ValueError, match='Missing user identity'):
            get_user_identity({})


# ── get_user_role ─────────────────────────────────────────────────────────────

class TestGetUserRole:
    def test_resolves_admin_from_string_group(self):
        event = _make_event(groups=ADMIN_GROUP)
        assert get_user_role(event) == UserRole.ADMIN

    def test_resolves_user_from_list_groups(self):
        # Cognito can deliver groups as a list depending on config.
        event = _make_event(groups=[USER_GROUP])
        assert get_user_role(event) == UserRole.USER

    def test_resolves_viewer_from_list_groups(self):
        event = _make_event(groups=[VIEWER_GROUP])
        assert get_user_role(event) == UserRole.VIEWER

    def test_admin_takes_precedence_over_user(self):
        # Authorisation policy: if a user somehow has both groups, admin wins.
        event = _make_event(groups=f'{ADMIN_GROUP} {USER_GROUP}')
        assert get_user_role(event) == UserRole.ADMIN

    def test_space_separated_groups_string(self):
        # Real Cognito format when a user belongs to multiple groups.
        event = _make_event(groups=f'{USER_GROUP} some-other-group')
        assert get_user_role(event) == UserRole.USER

    def test_bracket_wrapped_groups_string(self):
        # Cognito sometimes wraps groups in brackets: "[group1 group2]".
        # The strip('[]') logic exists specifically for this.
        event = _make_event(groups=f'[{VIEWER_GROUP}]')
        assert get_user_role(event) == UserRole.VIEWER

    def test_defaults_to_viewer_when_no_group(self):
        # Least-privilege fallback: users with no recognised group get viewer
        # access. This covers federated users on first login before the
        # post-auth Lambda assigns them to a group.
        event = _make_event(groups='')
        assert get_user_role(event) == UserRole.VIEWER

    def test_defaults_to_viewer_when_unknown_group(self):
        # Unrecognised group memberships fall back to viewer (least-privilege).
        event = _make_event(groups='some-unrecognised-group')
        assert get_user_role(event) == UserRole.VIEWER

    def test_defaults_to_viewer_when_event_empty(self):
        # Full defensive chain: no requestContext, no authorizer, no claims.
        assert get_user_role({}) == UserRole.VIEWER


# ── can_read_admin_views ──────────────────────────────────────────────────────

class TestCanReadAdminViews:
    """Contract: admin/privileged READ views (registry, standards, guardrail
    events) are readable by admins AND viewers, but NOT by the 'users' role.

    Viewer is a full-read, zero-write role (demo stakeholders). Writes to these
    resources stay admin-only — enforced separately on the mutating routes."""

    def test_admin_can_read(self):
        event = _make_event(groups=ADMIN_GROUP)
        assert can_read_admin_views(event) is True

    def test_viewer_can_read(self):
        event = _make_event(groups=VIEWER_GROUP)
        assert can_read_admin_views(event) is True

    def test_user_cannot_read(self):
        # The 'users' role is a project owner, not a privileged-view reader.
        # Guardrail events expose user emails; users must not see them.
        event = _make_event(groups=USER_GROUP)
        assert can_read_admin_views(event) is False

    def test_no_group_defaults_to_viewer_and_can_read(self):
        # get_user_role falls back to VIEWER for unrecognised/empty groups,
        # so an unknown-group caller is treated as a (read-only) viewer.
        event = _make_event(groups='')
        assert can_read_admin_views(event) is True

    def test_empty_event_defaults_to_viewer_and_can_read(self):
        assert can_read_admin_views({}) is True
