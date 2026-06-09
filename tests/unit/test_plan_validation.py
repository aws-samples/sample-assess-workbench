"""Unit tests for review plan validation.

Source: api/core/plan_validation.py
Contract: validate and sanitize AI-generated review plans, constraining to
          known agents, valid depths, and safe judge config bounds.
"""
from core.plan_validation import validate_plan, validate_judge_config, VALID_DEPTHS


AVAILABLE_AGENTS = {"architecture", "security", "risk"}


# ═══════════════════════════════════════════════════════════════════════════
# validate_judge_config
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateJudgeConfig:
    """Judge config comes from the AI planner or user input — it must be
    clamped to safe ranges regardless of what's provided."""

    def test_none_returns_disabled_defaults(self):
        result = validate_judge_config(None)
        assert result["enabled"] is False
        assert result["max_iterations"] == 3
        assert result["quality_threshold"] == 0.8

    def test_empty_dict_returns_disabled_defaults(self):
        result = validate_judge_config({})
        assert result["enabled"] is False

    def test_non_dict_returns_disabled_defaults(self):
        result = validate_judge_config("not a dict")
        assert result["enabled"] is False

    def test_valid_config_passes_through(self):
        result = validate_judge_config({
            "enabled": True,
            "max_iterations": 2,
            "quality_threshold": 0.9,
        })
        assert result == {"enabled": True, "max_iterations": 2, "quality_threshold": 0.9}

    def test_max_iterations_clamped_to_upper_bound(self):
        result = validate_judge_config({"max_iterations": 100})
        assert result["max_iterations"] == 5

    def test_max_iterations_clamped_to_lower_bound(self):
        result = validate_judge_config({"max_iterations": 0})
        assert result["max_iterations"] == 1

    def test_quality_threshold_clamped_to_upper_bound(self):
        result = validate_judge_config({"quality_threshold": 5.0})
        assert result["quality_threshold"] == 1.0

    def test_quality_threshold_clamped_to_lower_bound(self):
        result = validate_judge_config({"quality_threshold": 0.1})
        assert result["quality_threshold"] == 0.5

    def test_non_numeric_iterations_defaults_to_1(self):
        result = validate_judge_config({"max_iterations": "fast"})
        assert result["max_iterations"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# validate_plan
# ═══════════════════════════════════════════════════════════════════════════

class TestValidatePlan:
    """The planner produces a plan dict with groups of agents. validate_plan
    must enforce constraints and fall back gracefully."""

    def test_valid_plan_passes_through(self):
        plan = {
            "groups": [{
                "group_id": "g1",
                "label": "Core Review",
                "execution": "parallel",
                "agents": [
                    {"agent_type": "architecture", "depth": "thorough"},
                    {"agent_type": "security", "depth": "standard"},
                ],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        agent_types = [a["agent_type"] for a in result["groups"][0]["agents"]]
        assert agent_types == ["architecture", "security"]

    def test_unknown_agent_type_is_removed(self):
        plan = {
            "groups": [{
                "group_id": "g1",
                "label": "Review",
                "execution": "parallel",
                "agents": [
                    {"agent_type": "architecture"},
                    {"agent_type": "made_up_agent"},
                ],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        agent_types = [a["agent_type"] for a in result["groups"][0]["agents"]]
        assert "made_up_agent" not in agent_types
        assert "architecture" in agent_types

    def test_duplicate_agent_kept_only_once(self):
        plan = {
            "groups": [
                {"agents": [{"agent_type": "security"}]},
                {"agents": [{"agent_type": "security"}]},
            ]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        all_agents = [
            a["agent_type"]
            for g in result["groups"]
            for a in g["agents"]
        ]
        assert all_agents.count("security") == 1

    def test_invalid_depth_defaults_to_standard(self):
        plan = {
            "groups": [{
                "agents": [{"agent_type": "risk", "depth": "ultra_deep"}],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        assert result["groups"][0]["agents"][0]["depth"] == "standard"

    def test_all_valid_depths_accepted(self):
        for depth in VALID_DEPTHS:
            plan = {"groups": [{"agents": [{"agent_type": "architecture", "depth": depth}]}]}
            result = validate_plan(plan, AVAILABLE_AGENTS)
            assert result["groups"][0]["agents"][0]["depth"] == depth

    def test_invalid_execution_defaults_to_parallel(self):
        plan = {
            "groups": [{
                "execution": "random_order",
                "agents": [{"agent_type": "architecture"}],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        assert result["groups"][0]["execution"] == "parallel"

    def test_sequential_execution_accepted(self):
        plan = {
            "groups": [{
                "execution": "sequential",
                "agents": [{"agent_type": "architecture"}],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        assert result["groups"][0]["execution"] == "sequential"

    def test_focus_areas_truncated_to_10(self):
        plan = {
            "groups": [{
                "agents": [{
                    "agent_type": "security",
                    "focus_areas": [f"area_{i}" for i in range(20)],
                }],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        assert len(result["groups"][0]["agents"][0]["focus_areas"]) == 10

    def test_prompt_addendum_truncated_to_1000_chars(self):
        plan = {
            "groups": [{
                "agents": [{
                    "agent_type": "architecture",
                    "prompt_addendum": "x" * 2000,
                }],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        assert len(result["groups"][0]["agents"][0]["prompt_addendum"]) == 1000

    def test_empty_plan_falls_back_to_default(self):
        """A plan with no usable groups should produce a default parallel group
        containing all available agents."""
        result = validate_plan({"groups": []}, AVAILABLE_AGENTS)
        assert len(result["groups"]) == 1
        assert result["groups"][0]["group_id"] == "default_parallel"
        assert result["groups"][0]["execution"] == "parallel"
        fallback_types = {a["agent_type"] for a in result["groups"][0]["agents"]}
        assert fallback_types == AVAILABLE_AGENTS

    def test_plan_with_only_unknown_agents_falls_back(self):
        plan = {
            "groups": [{
                "agents": [{"agent_type": "nonexistent"}],
            }]
        }
        result = validate_plan(plan, AVAILABLE_AGENTS)
        assert result["groups"][0]["group_id"] == "default_parallel"
