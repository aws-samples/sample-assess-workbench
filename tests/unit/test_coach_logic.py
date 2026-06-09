"""Unit tests for coach loop logic — imported from real source.

Tests the pure functions and constants in api/core/coach_logic.py:
  - build_org_context
  - build_judge_prompt
  - enrich_plan_with_guidance
  - normalize_evaluation
  - check_early_exit
  - JUDGE_TOOL
"""

from core.coach_logic import (
    build_org_context,
    build_judge_prompt,
    enrich_plan_with_guidance,
    normalize_evaluation,
    check_early_exit,
    JUDGE_TOOL,
)


# ═══════════════════════════════════════════════════════════════════════════
# build_org_context
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildOrgContext:

    def test_base_context_with_default_standard_depth(self):
        """Default depth is 'standard', which always appends depth instructions."""
        result = build_org_context("Base context")
        assert result.startswith("Base context")
        assert "--- Depth: Standard ---" in result
        assert "5-8 findings" in result

    def test_empty_base_context_still_gets_depth(self):
        """Even with empty base context, standard depth instructions are appended."""
        result = build_org_context("")
        assert "--- Depth: Standard ---" in result
        assert "5-8 findings" in result

    def test_appends_prompt_addendum(self):
        result = build_org_context("Base", prompt_addendum="Focus on auth")
        assert "--- Review Plan Guidance ---" in result
        assert "Focus on auth" in result

    def test_appends_depth_quick(self):
        result = build_org_context("Base", depth="quick")
        assert "--- Depth: Quick ---" in result
        assert "3-5 findings" in result

    def test_appends_depth_thorough(self):
        result = build_org_context("Base", depth="thorough")
        assert "--- Depth: Thorough ---" in result
        assert "exhaustive" in result

    def test_standard_depth_adds_guidance(self):
        result = build_org_context("Base", depth="standard")
        assert "5-8 findings" in result

    def test_appends_focus_areas(self):
        result = build_org_context("Base", focus_areas=["auth", "encryption"])
        assert "--- Focus Areas ---" in result
        assert "auth, encryption" in result

    def test_coach_feedback_includes_prior_findings(self):
        findings = [{"id": "SEC-001", "title": "Weak auth"}]
        result = build_org_context(
            "Base", prior_critique="Needs more depth",
            prior_findings=findings, iteration=1,
        )
        assert "--- Your Prior Findings (Iteration 1) ---" in result
        assert "SEC-001" in result

    def test_coach_feedback_includes_strengths_and_gaps(self):
        result = build_org_context(
            "Base", prior_critique="Improve specificity",
            prior_strengths=["Good coverage of auth"],
            prior_gaps=["Missing encryption analysis"],
            iteration=1,
        )
        assert "✓ Good coverage of auth" in result
        assert "✗ Missing encryption analysis" in result

    def test_coach_feedback_includes_critique(self):
        result = build_org_context(
            "Base", prior_critique="Add OWASP mappings",
            iteration=2,
        )
        assert "--- Quality Judge Feedback (Iteration 2) ---" in result
        assert "Add OWASP mappings" in result
        assert "You MUST keep every finding" in result

    def test_no_coach_feedback_on_iteration_zero(self):
        result = build_org_context(
            "Base", prior_critique="Some critique", iteration=0,
        )
        assert "Quality Judge Feedback" not in result

    def test_no_coach_feedback_without_critique(self):
        result = build_org_context(
            "Base", prior_findings=[{"id": "X"}], iteration=1,
        )
        assert "Quality Judge Feedback" not in result


# ═══════════════════════════════════════════════════════════════════════════
# build_judge_prompt
# ═══════════════════════════════════════════════════════════════════════════

    def test_includes_agent_type(self):
        result = build_judge_prompt("security", 0.8, "", "doc", ["auth"], [])
        assert "security reviews" in result

    def test_includes_coach_guidance(self):
        guidance = "Check OWASP mappings are accurate"
        result = build_judge_prompt("security", 0.8, guidance, "doc", [], [])
        assert guidance in result

    def test_empty_coach_guidance(self):
        result = build_judge_prompt("security", 0.8, "", "doc preview", [], [])
        assert "doc preview" in result

    def test_document_preview_capped_at_10000(self):
        long_doc = "z" * 20000
        result = build_judge_prompt("arch", 0.8, "", long_doc, [], [])
        # The prompt should contain at most 10000 z's from the document
        assert result.count("z") <= 10000

    def test_findings_json_capped_at_16000(self):
        big_findings = [{"id": f"F-{i}", "desc": "y" * 500} for i in range(100)]
        result = build_judge_prompt("arch", 0.8, "", "doc", [], big_findings)
        # Full JSON would be ~60K; should be truncated
        assert len(result) < 30000

    def test_coach_mode_appends_prior_critique(self):
        result = build_judge_prompt(
            "security", 0.8, "", "doc", [], [],
            mode="coach", iteration=2, prior_critique="Missing encryption",
        )
        assert "Prior critique (iteration 2):" in result
        assert "Missing encryption" in result

    def test_evaluate_mode_no_prior_critique(self):
        result = build_judge_prompt(
            "security", 0.8, "", "doc", [], [],
            mode="evaluate", iteration=0, prior_critique="Should not appear",
        )
        assert "Prior critique" not in result

    def test_quality_threshold_in_prompt(self):
        result = build_judge_prompt("arch", 0.75, "", "doc", [], [])
        assert "0.75" in result

    def test_focus_areas_serialized(self):
        result = build_judge_prompt("arch", 0.8, "", "doc", ["scalability", "caching"], [])
        assert "scalability" in result
        assert "caching" in result


# ═══════════════════════════════════════════════════════════════════════════
# enrich_plan_with_guidance
# ═══════════════════════════════════════════════════════════════════════════

class TestEnrichPlanWithGuidance:

    def _make_plan(self, agents):
        return {
            "groups": [{
                "group_id": "g1", "label": "Group 1",
                "execution": "parallel", "agents": agents,
            }]
        }

    def _make_registry(self, entries):
        return {k: v for k, v in entries.items()}

    def test_injects_coach_guidance_from_registry(self):
        plan = self._make_plan([
            {"agent_type": "security", "judge": {"enabled": False}, "coach_guidance": ""},
        ])
        registry = {"security": {"coach_guidance": "Check OWASP mappings"}}
        result = enrich_plan_with_guidance(plan, registry)
        assert result["groups"][0]["agents"][0]["coach_guidance"] == "Check OWASP mappings"

    def test_auto_disables_coach_when_no_guidance(self):
        plan = self._make_plan([
            {"agent_type": "security", "judge": {"enabled": True, "max_iterations": 3}},
        ])
        registry = {"security": {}}  # No coach_guidance
        result = enrich_plan_with_guidance(plan, registry)
        assert result["groups"][0]["agents"][0]["judge"]["enabled"] is False

    def test_warning_added_when_coach_disabled(self):
        plan = self._make_plan([
            {"agent_type": "security", "judge": {"enabled": True}},
        ])
        registry = {"security": {}}
        result = enrich_plan_with_guidance(plan, registry)
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["agent_type"] == "security"
        assert "no coach guidance" in result["warnings"][0]["message"].lower()

    def test_no_warning_when_guidance_present(self):
        plan = self._make_plan([
            {"agent_type": "security", "judge": {"enabled": True}},
        ])
        registry = {"security": {"coach_guidance": "Some guidance"}}
        result = enrich_plan_with_guidance(plan, registry)
        assert "warnings" not in result

    def test_no_warning_when_coach_disabled(self):
        plan = self._make_plan([
            {"agent_type": "security", "judge": {"enabled": False}},
        ])
        registry = {"security": {}}  # No guidance, but coach is off
        result = enrich_plan_with_guidance(plan, registry)
        assert "warnings" not in result

    def test_multiple_agents_mixed(self):
        plan = self._make_plan([
            {"agent_type": "security", "judge": {"enabled": True}},
            {"agent_type": "architecture", "judge": {"enabled": True}},
            {"agent_type": "risk", "judge": {"enabled": False}},
        ])
        registry = {
            "security": {"coach_guidance": "Security guidance"},
            "architecture": {},  # No guidance — should warn
            "risk": {},  # No guidance but coach off — no warn
        }
        result = enrich_plan_with_guidance(plan, registry)
        agents = result["groups"][0]["agents"]
        # Security: coach stays on
        assert agents[0]["judge"]["enabled"] is True
        assert agents[0]["coach_guidance"] == "Security guidance"
        # Architecture: coach auto-disabled
        assert agents[1]["judge"]["enabled"] is False
        # Risk: coach was already off
        assert agents[2]["judge"]["enabled"] is False
        # Only one warning (architecture)
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["agent_type"] == "architecture"

    def test_default_depth_overrides_planner(self):
        plan = self._make_plan([
            {"agent_type": "security", "depth": "quick", "judge": {"enabled": False}},
        ])
        registry = {"security": {"default_depth": "thorough"}}
        result = enrich_plan_with_guidance(plan, registry)
        assert result["groups"][0]["agents"][0]["depth"] == "thorough"

    def test_default_depth_empty_does_not_override(self):
        plan = self._make_plan([
            {"agent_type": "security", "depth": "quick", "judge": {"enabled": False}},
        ])
        registry = {"security": {"default_depth": ""}}
        result = enrich_plan_with_guidance(plan, registry)
        assert result["groups"][0]["agents"][0]["depth"] == "quick"

    def test_default_depth_missing_does_not_override(self):
        plan = self._make_plan([
            {"agent_type": "security", "depth": "standard", "judge": {"enabled": False}},
        ])
        registry = {"security": {}}
        result = enrich_plan_with_guidance(plan, registry)
        assert result["groups"][0]["agents"][0]["depth"] == "standard"

    def test_default_depth_invalid_value_ignored(self):
        plan = self._make_plan([
            {"agent_type": "security", "depth": "standard", "judge": {"enabled": False}},
        ])
        registry = {"security": {"default_depth": "ultra"}}
        result = enrich_plan_with_guidance(plan, registry)
        assert result["groups"][0]["agents"][0]["depth"] == "standard"


# ═══════════════════════════════════════════════════════════════════════════
# normalize_evaluation
#
# Recalculates judge scores with consistent float handling. The key
# subtlety: it truncates (floors) to 2 decimal places rather than
# rounding, so a score of 0.7966... becomes 0.79, not 0.80. This
# prevents borderline scores from rounding up to meet the threshold.
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeEvaluation:

    def test_recalculates_overall_from_criteria(self):
        evaluation = {
            'scores_by_criterion': {
                'completeness': 0.9,
                'specificity': 0.8,
                'actionability': 0.7,
            },
        }
        result, overall, raw_avg = normalize_evaluation(evaluation, 0.8)
        assert overall == 0.8  # (0.9+0.8+0.7)/3 = 0.8
        assert result['overall_score'] == 0.8

    def test_truncates_down_not_rounds_up(self):
        """0.7966... should become 0.79, not 0.80. This is the whole point
        of the truncation logic — prevent gaming the threshold."""
        evaluation = {
            'scores_by_criterion': {
                'completeness': 0.8,
                'specificity': 0.8,
                'actionability': 0.79,
            },
        }
        _, overall, _ = normalize_evaluation(evaluation, 0.8)
        # (0.8 + 0.8 + 0.79) / 3 = 0.7966...
        assert overall == 0.79
        assert overall < 0.80

    def test_quality_met_when_at_threshold(self):
        evaluation = {
            'scores_by_criterion': {
                'completeness': 0.8,
                'specificity': 0.8,
                'actionability': 0.8,
            },
        }
        result, _, _ = normalize_evaluation(evaluation, 0.8)
        assert result['quality_met'] is True

    def test_quality_not_met_below_threshold(self):
        evaluation = {
            'scores_by_criterion': {
                'completeness': 0.7,
                'specificity': 0.7,
                'actionability': 0.7,
            },
        }
        result, _, _ = normalize_evaluation(evaluation, 0.8)
        assert result['quality_met'] is False

    def test_missing_scores_default_to_zero(self):
        evaluation = {'scores_by_criterion': {}}
        result, overall, _ = normalize_evaluation(evaluation, 0.8)
        assert overall == 0.0
        assert result['scores_by_criterion']['completeness'] == 0
        assert result['quality_met'] is False

    def test_defaults_added_for_missing_fields(self):
        evaluation = {'scores_by_criterion': {'completeness': 1, 'specificity': 1, 'actionability': 1}}
        result, _, _ = normalize_evaluation(evaluation, 0.8)
        assert result['critique'] == ''
        assert result['strengths'] == []
        assert result['gaps'] == []

    def test_existing_fields_not_overwritten(self):
        evaluation = {
            'scores_by_criterion': {'completeness': 1, 'specificity': 1, 'actionability': 1},
            'critique': 'Needs more detail',
            'strengths': ['Good coverage'],
            'gaps': ['Missing auth analysis'],
        }
        result, _, _ = normalize_evaluation(evaluation, 0.8)
        assert result['critique'] == 'Needs more detail'
        assert result['strengths'] == ['Good coverage']
        assert result['gaps'] == ['Missing auth analysis']

    def test_string_scores_converted_to_float(self):
        """The model might return scores as strings — should still work."""
        evaluation = {
            'scores_by_criterion': {
                'completeness': '0.9',
                'specificity': '0.8',
                'actionability': '0.7',
            },
        }
        _, overall, _ = normalize_evaluation(evaluation, '0.8')
        assert overall == 0.8


# ═══════════════════════════════════════════════════════════════════════════
# check_early_exit
#
# Detects score regression in coach mode. After 2 consecutive drops,
# forces quality_met=True to stop the coaching loop. Without this,
# a struggling agent could loop forever getting worse each time.
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckEarlyExit:

    def test_evaluate_mode_always_returns_empty(self):
        evaluation = {'quality_met': False}
        reason, drops = check_early_exit(evaluation, 0.5, 'evaluate', 1, 0.6, 0)
        assert reason == ''
        assert drops == 0

    def test_quality_already_met_returns_empty(self):
        evaluation = {'quality_met': True}
        reason, drops = check_early_exit(evaluation, 0.9, 'coach', 2, 0.8, 1)
        assert reason == ''

    def test_first_iteration_no_drop(self):
        evaluation = {'quality_met': False}
        reason, drops = check_early_exit(evaluation, 0.5, 'coach', 0, 0, 0)
        assert reason == ''
        assert drops == 0

    def test_single_drop_increments_counter(self):
        evaluation = {'quality_met': False}
        reason, drops = check_early_exit(evaluation, 0.5, 'coach', 1, 0.6, 0)
        assert reason == ''
        assert drops == 1

    def test_two_consecutive_drops_triggers_exit(self):
        evaluation = {'quality_met': False}
        reason, drops = check_early_exit(evaluation, 0.4, 'coach', 2, 0.5, 1)
        assert reason == 'score_declining'
        assert drops == 2
        assert evaluation['quality_met'] is True

    def test_improvement_resets_counter(self):
        """If the score improves after a drop, the counter resets."""
        evaluation = {'quality_met': False}
        reason, drops = check_early_exit(evaluation, 0.7, 'coach', 2, 0.6, 1)
        assert reason == ''
        assert drops == 0

    def test_equal_score_resets_counter(self):
        """Same score as prior is not a drop."""
        evaluation = {'quality_met': False}
        reason, drops = check_early_exit(evaluation, 0.6, 'coach', 1, 0.6, 1)
        assert reason == ''
        assert drops == 0

# ═══════════════════════════════════════════════════════════════════════════
# JUDGE_TOOL schema
# ═══════════════════════════════════════════════════════════════════════════


class TestJudgeTool:
    """JUDGE_TOOL is the Bedrock tool schema shared by invoke_judge and run_benchmark.

    An import error on this constant broke the benchmark runner Lambda at init
    time (No module named 'workflow'). These tests ensure the schema stays
    importable from core.coach_logic and structurally valid.
    """

    def test_tool_name_is_submit_evaluation(self):
        assert JUDGE_TOOL['toolSpec']['name'] == 'submit_evaluation'

    def test_required_scoring_fields_present(self):
        required = JUDGE_TOOL['toolSpec']['inputSchema']['json']['required']
        assert 'quality_met' in required
        assert 'overall_score' in required
        assert 'scores_by_criterion' in required
        assert 'strengths' in required
        assert 'gaps' in required

    def test_scoring_criteria_present(self):
        criteria = (
            JUDGE_TOOL['toolSpec']['inputSchema']['json']
            ['properties']['scores_by_criterion']['properties']
        )
        assert 'completeness' in criteria
        assert 'specificity' in criteria
        assert 'actionability' in criteria
