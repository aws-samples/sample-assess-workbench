"""Unit tests for per-user chat session scoping.

These assert the storage-key contract that isolates one user's chat
sessions and messages from another's on a shared project. The keys embed
``user_sub`` so a user can only ever address their own partition — even
if they knew another user's ``session_id``, the key built from their own
``user_sub`` would not match it.

Pure logic only — the key builders touch no AWS. A full cross-user
round-trip against DynamoDB belongs in tests/live/ once per-role Cognito
test users exist (see roadmap: "Cross-role multi-tenancy live tests").
"""

import pytest

from core.chat import (
    _session_sk,
    _session_sk_prefix,
    _message_sk_prefix,
    create_chat_session,
    list_chat_sessions,
    delete_chat_session,
    store_chat_message,
    update_session_metadata,
    load_chat_history,
    load_chat_messages,
)

AGENT = "security"
SESSION = "11111111-2222-3333-4444-555555555555"
USER_A = "sub-aaaa"
USER_B = "sub-bbbb"


class TestSessionKeyScoping:
    """The session sort key must embed user_sub and partition by user."""

    def test_session_sk_contains_user_sub(self):
        sk = _session_sk(USER_A, AGENT, SESSION)
        assert sk == f"CHATSESSION#{USER_A}#{AGENT}#{SESSION}"

    def test_different_users_get_different_session_keys(self):
        sk_a = _session_sk(USER_A, AGENT, SESSION)
        sk_b = _session_sk(USER_B, AGENT, SESSION)
        # Same agent + session_id, different user → different physical key.
        assert sk_a != sk_b

    def test_session_prefix_is_user_scoped(self):
        prefix = _session_sk_prefix(USER_A, AGENT)
        assert prefix == f"CHATSESSION#{USER_A}#{AGENT}#"

    def test_one_users_session_key_does_not_match_anothers_prefix(self):
        """User B's listing prefix must not match user A's session key."""
        sk_a = _session_sk(USER_A, AGENT, SESSION)
        prefix_b = _session_sk_prefix(USER_B, AGENT)
        assert not sk_a.startswith(prefix_b)


class TestMessageKeyScoping:
    """The message sort key must embed user_sub and partition by user."""

    def test_message_prefix_contains_user_sub(self):
        prefix = _message_sk_prefix(USER_A, AGENT, SESSION)
        assert prefix == f"CHAT#{USER_A}#{AGENT}#{SESSION}#"

    def test_different_users_get_different_message_prefixes(self):
        prefix_a = _message_sk_prefix(USER_A, AGENT, SESSION)
        prefix_b = _message_sk_prefix(USER_B, AGENT, SESSION)
        assert prefix_a != prefix_b

    def test_one_users_message_prefix_does_not_match_anothers(self):
        """User A's messages must be unreachable under user B's prefix."""
        prefix_a = _message_sk_prefix(USER_A, AGENT, SESSION)
        prefix_b = _message_sk_prefix(USER_B, AGENT, SESSION)
        assert not prefix_a.startswith(prefix_b)
        assert not prefix_b.startswith(prefix_a)


class TestUserSubRequired:
    """Every public chat function must reject an empty user_sub.

    An empty user_sub would collapse all users into a shared partition
    (the original bug). The functions guard against it before touching
    the key, so the failure is loud rather than a silent data leak.

    A dummy object stands in for the DynamoDB table — these calls must
    raise before any table method is invoked.
    """

    class _ExplodingTable:
        """Any attribute access fails the test — the guard must fire first."""

        def __getattr__(self, name):  # pragma: no cover - defensive
            raise AssertionError(
                f"DynamoDB '{name}' called despite empty user_sub — "
                "the guard should raise before any table access"
            )

    @pytest.fixture
    def table(self):
        return self._ExplodingTable()

    def test_create_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            create_chat_session(table, "proj", "", AGENT)

    def test_list_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            list_chat_sessions(table, "proj", "", AGENT)

    def test_delete_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            delete_chat_session(table, "proj", "", AGENT, SESSION)

    def test_store_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            store_chat_message(table, "proj", "", AGENT, SESSION, "hi", "hello")

    def test_update_metadata_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            update_session_metadata(table, "proj", "", AGENT, SESSION, "hi")

    def test_load_history_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            load_chat_history(table, "proj", "", AGENT, SESSION)

    def test_load_messages_requires_user_sub(self, table):
        with pytest.raises(ValueError, match="user_sub"):
            load_chat_messages(table, "proj", "", AGENT, SESSION)
