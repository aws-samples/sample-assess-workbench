"""Unit tests for the shared review-lifecycle helpers.

Covers the pure-logic surface of tests/live/lifecycle.py — the plan-group
builder. The lifecycle driver itself (run_review_lifecycle) hits the live API
and is exercised by the live suite, not here.
"""

import pytest

from tests.live.lifecycle import (
    DEFAULT_PLAN_GROUPS,
    JUDGE_OFF,
    build_groups,
)


class TestBuildGroups:
    """build_groups maps a sequence of agent-type lists to approve-plan groups.

    Contract: each inner list is one group (agents run in parallel within a
    group); groups run sequentially in order. depth and judge apply to every
    agent; judge defaults to JUDGE_OFF.
    """

    def test_sequential_groups_one_agent_each(self):
        """A list of single-agent lists yields one group per agent, in order."""
        groups = build_groups([["architecture"], ["security"]])
        assert len(groups) == 2
        assert [a["agent_type"] for g in groups for a in g["agents"]] == [
            "architecture",
            "security",
        ]
        assert all(len(g["agents"]) == 1 for g in groups)

    def test_parallel_group(self):
        """A single list with multiple agents yields one group running them all."""
        groups = build_groups([["architecture", "security"]])
        assert len(groups) == 1
        assert [a["agent_type"] for a in groups[0]["agents"]] == ["architecture", "security"]

    def test_default_depth_is_quick(self):
        """Every agent gets depth 'quick' unless overridden."""
        groups = build_groups([["risk"]])
        assert groups[0]["agents"][0]["depth"] == "quick"

    def test_custom_depth_applies_to_all_agents(self):
        """An explicit depth is applied to every agent in every group."""
        groups = build_groups([["architecture", "security"], ["risk"]], depth="standard")
        depths = [a["depth"] for g in groups for a in g["agents"]]
        assert depths == ["standard", "standard", "standard"]

    def test_default_judge_is_judge_off(self):
        """Without an explicit judge, every agent carries JUDGE_OFF."""
        groups = build_groups([["architecture"]])
        assert groups[0]["agents"][0]["judge"] == JUDGE_OFF

    def test_custom_judge_applies_to_all_agents(self):
        """An explicit judge config replaces JUDGE_OFF for every agent."""
        judge = {"enabled": True, "max_iterations": 2, "quality_threshold": 0.8}
        groups = build_groups([["architecture"], ["security"]], judge=judge)
        for g in groups:
            for a in g["agents"]:
                assert a["judge"] == judge

    def test_empty_sequence_yields_no_groups(self):
        """An empty sequence produces an empty group list."""
        assert build_groups([]) == []

    def test_agent_dict_shape_matches_approve_contract(self):
        """Each agent dict has exactly the keys the approve endpoint expects."""
        groups = build_groups([["architecture"]])
        agent = groups[0]["agents"][0]
        assert set(agent.keys()) == {"agent_type", "depth", "judge"}


class TestDefaultPlanGroups:
    """The exported default reproduces the original live-test plan."""

    def test_default_is_architecture_then_security_sequential(self):
        """DEFAULT_PLAN_GROUPS = architecture, then security, judge disabled."""
        assert DEFAULT_PLAN_GROUPS == build_groups([["architecture"], ["security"]])
        agent_types = [a["agent_type"] for g in DEFAULT_PLAN_GROUPS for a in g["agents"]]
        assert agent_types == ["architecture", "security"]
        assert all(
            a["judge"] == JUDGE_OFF and a["depth"] == "quick"
            for g in DEFAULT_PLAN_GROUPS
            for a in g["agents"]
        )

    def test_judge_off_is_disabled(self):
        """JUDGE_OFF disables the judge — a guard so the default stays fast."""
        assert JUDGE_OFF["enabled"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
