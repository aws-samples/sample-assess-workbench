"""Contract tests for core.registry ARN resolution.

load_agent_arns builds the SSM prefix /{project}/{environment}/agent/ from
PROJECT_NAME and ENVIRONMENT. Those must fail loud when unset rather than
silently defaulting to a hardcoded tenant — a silent default would resolve
zero agents under a renamed project. The tenant check runs before any AWS
call, so this is exercisable offline.
"""

import pytest

import core.registry as registry
from core.registry import load_agent_arns


class TestLoadAgentArnsRequiresTenantEnv:
    """PROJECT_NAME and ENVIRONMENT are required, not defaulted."""

    def _clear_caches(self):
        registry._agent_arns_cache.clear()
        registry._agent_arns_cache_time.clear()

    def test_missing_project_name_raises(self, monkeypatch):
        self._clear_caches()
        monkeypatch.delenv("PROJECT_NAME", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "dev")
        with pytest.raises(RuntimeError, match="PROJECT_NAME and ENVIRONMENT"):
            load_agent_arns(table_name="dummy-table", role="review")

    def test_missing_environment_raises(self, monkeypatch):
        self._clear_caches()
        monkeypatch.setenv("PROJECT_NAME", "acme")
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        with pytest.raises(RuntimeError, match="PROJECT_NAME and ENVIRONMENT"):
            load_agent_arns(table_name="dummy-table", role="chat")
