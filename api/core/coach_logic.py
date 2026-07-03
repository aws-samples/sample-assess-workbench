"""Pure logic for the coach feedback loop.

Contains functions used by the review agent invoker, judge evaluator,
and plan enrichment — extracted for testability and reuse.

No AWS dependencies — only stdlib imports.
"""

import json


# ── Depth instructions appended to organizational context ──

DEPTH_INSTRUCTIONS = {
    "quick": (
        "\n\n--- Depth: Quick ---\n"
        "Provide a surface-level review. Focus on the most critical issues only. "
        "Aim for 3-5 findings."
    ),
    "standard": (
        "\n\n--- Depth: Standard ---\n"
        "Provide a balanced review. Focus on the most impactful issues. "
        "Aim for 5-8 findings."
    ),
    "thorough": (
        "\n\n--- Depth: Thorough ---\n"
        "Provide an exhaustive review. Examine every aspect in detail. "
        "Aim for 8-12 findings. Be comprehensive but prioritize — "
        "every finding should be actionable."
    ),
}


# ── Judge tool schema (shared by invoke_judge) ──

JUDGE_TOOL = {
    "toolSpec": {
        "name": "submit_evaluation",
        "description": "Submit the quality evaluation scores and critique.",
        "inputSchema": {
            "json": {
                "type": "object",
                "required": [
                    "quality_met",
                    "overall_score",
                    "scores_by_criterion",
                    "strengths",
                    "gaps",
                ],
                "properties": {
                    "quality_met": {
                        "type": "boolean",
                        "description": "Whether the overall score meets the quality threshold",
                    },
                    "overall_score": {
                        "type": "number",
                        "description": "Average of all criterion scores (0.0 to 1.0)",
                    },
                    "scores_by_criterion": {
                        "type": "object",
                        "required": ["completeness", "specificity", "actionability"],
                        "properties": {
                            "completeness": {"type": "number"},
                            "specificity": {"type": "number"},
                            "actionability": {"type": "number"},
                        },
                    },
                    "critique": {
                        "type": "string",
                        "description": "Specific feedback for improvement (empty if quality met)",
                    },
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What the agent did well",
                    },
                    "gaps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "What is missing or weak",
                    },
                },
            }
        },
    }
}


# ── Judge prompt template ──

JUDGE_PROMPT = """You are a quality judge for {agent_type} reviews. Evaluate the following findings against the document and focus areas.

Score each criterion from 0.0 to 1.0:
- completeness: Are all relevant aspects of the focus areas covered? Are there obvious gaps?
- specificity: Do findings reference specific parts of the document? Are descriptions precise rather than generic?
- actionability: Can a team act on each finding without further clarification? Are recommendations concrete?

Quality threshold: {quality_threshold}

If the average score meets the threshold, set quality_met to true.
If not, provide specific critique explaining what's missing or weak.
Be constructive — in coach mode, the agent will use your feedback to improve.

{schema_guidance}

Document preview:
{document_preview}

Focus areas: {focus_areas}

Findings to evaluate:
{findings_json}"""


# ── Build organizational context for a review agent ──


def build_org_context(
    base_context,
    depth="standard",
    focus_areas=None,
    prompt_addendum="",
    prior_critique="",
    prior_findings=None,
    prior_strengths=None,
    prior_gaps=None,
    iteration=0,
):
    """Assemble the organizational context string for a review agent.

    Appends depth instructions, focus areas, and coach feedback (if applicable)
    to the base organizational context.

    Args:
        base_context: Base organizational context string from the document.
        depth: Review depth — 'quick', 'standard', or 'thorough'.
        focus_areas: List of focus area strings to prioritize.
        prompt_addendum: Document-specific guidance from the review plan.
        prior_critique: Judge critique from the previous iteration.
        prior_findings: Agent findings from the previous iteration.
        prior_strengths: Strengths identified by the judge in the previous iteration.
        prior_gaps: Gaps identified by the judge in the previous iteration.
        iteration: Current coach loop iteration (0 = first run).

    Returns:
        Assembled organizational context string.
    """
    org_context = base_context or ""

    if prompt_addendum:
        org_context += f"\n\n--- Review Plan Guidance ---\n{prompt_addendum}"

    depth_instr = DEPTH_INSTRUCTIONS.get(depth, "")
    if depth_instr:
        org_context += depth_instr

    if focus_areas:
        org_context += f"\n\n--- Focus Areas ---\nPrioritize these areas: {', '.join(focus_areas)}"

    if prior_critique and iteration > 0:
        if prior_findings:
            org_context += f"\n\n--- Your Prior Findings (Iteration {iteration}) ---\n"
            org_context += json.dumps(prior_findings, indent=None)[:8000]
            org_context += "\n"

        org_context += f"\n\n--- Quality Judge Feedback (Iteration {iteration}) ---\n"
        if prior_strengths:
            org_context += "MANDATORY — preserve these findings exactly as-is (do not modify, remove, or weaken):\n"
            for s in prior_strengths:
                org_context += f"  ✓ {s}\n"
        if prior_gaps:
            org_context += "Gaps to fix:\n"
            for g in prior_gaps:
                org_context += f"  ✗ {g}\n"
        org_context += f"\nDetailed critique:\n{prior_critique}\n"
        org_context += (
            "\nYou MUST keep every finding listed under strengths unchanged. "
            "Fix or replace only the findings called out in gaps. "
            "Add new findings for uncovered gaps. "
            "Do not reduce the total number of findings.\n"
        )

    return org_context


# ── Build judge evaluation prompt ──


def build_judge_prompt(
    agent_type,
    quality_threshold,
    coach_guidance,
    document_preview,
    focus_areas,
    findings,
    mode="evaluate",
    iteration=0,
    prior_critique="",
):
    """Build the judge evaluation prompt.

    Assembles the prompt from the template, coach guidance, document preview,
    and findings. Applies truncation caps to prevent token bloat.

    Returns:
        Formatted prompt string.
    """
    doc_preview = (document_preview or "")[:10000]
    findings_json = json.dumps(findings, indent=None)[:16000]

    prompt_text = JUDGE_PROMPT.format(
        agent_type=agent_type,
        quality_threshold=quality_threshold,
        schema_guidance=coach_guidance or "",
        document_preview=doc_preview,
        focus_areas=json.dumps(focus_areas),
        findings_json=findings_json,
    )

    if mode == "coach" and prior_critique:
        prompt_text += f"\n\nPrior critique (iteration {iteration}):\n{prior_critique}"

    return prompt_text


# ── Enrich plan with coach guidance from registry ──


def enrich_plan_with_guidance(plan, available_agents):
    """Enrich plan agents with registry overrides for depth, coach, and judge.

    For each agent in the plan:
    - Injects coach_guidance from the registry.
    - Applies default_depth from the registry as override over the planner's value.
    - Applies judge_defaults from the registry as overrides (quality_threshold,
      max_iterations, coach_enabled) over the planner's values.
    - The user can still customize all of these in the plan approval UI
      before execution.
    - If an agent has coaching enabled but no guidance configured, auto-disables
      coaching and adds a warning.

    Precedence: planner suggests → registry overrides → user customizes in UI.

    Args:
        plan: Validated plan dict with groups/agents.
        available_agents: Registry dict mapping agent_type to registry entry.

    Returns:
        Plan dict with registry overrides applied and warnings added.
    """
    warnings = []
    for group in plan.get("groups", []):
        for agent in group.get("agents", []):
            agent_type = agent.get("agent_type", "")
            registry_entry = available_agents.get(agent_type, {})
            coach_guidance = registry_entry.get("coach_guidance", "")
            agent["coach_guidance"] = coach_guidance

            # Apply default_depth from registry as override
            default_depth = registry_entry.get("default_depth", "")
            if default_depth in ("quick", "standard", "thorough"):
                agent["depth"] = default_depth

            # Apply judge_defaults from registry as overrides
            judge_defaults = registry_entry.get("judge_defaults", "")
            if isinstance(judge_defaults, str) and judge_defaults:
                try:
                    judge_defaults = json.loads(judge_defaults)
                except (json.JSONDecodeError, TypeError):
                    judge_defaults = {}
            if isinstance(judge_defaults, dict) and judge_defaults:
                judge = agent.get("judge", {})
                if "quality_threshold" in judge_defaults:
                    try:
                        judge["quality_threshold"] = round(
                            float(judge_defaults["quality_threshold"]), 2
                        )
                    except (ValueError, TypeError):
                        pass
                if "max_iterations" in judge_defaults:
                    try:
                        judge["max_iterations"] = int(judge_defaults["max_iterations"])
                    except (ValueError, TypeError):
                        pass
                if "coach_enabled" in judge_defaults:
                    judge["enabled"] = bool(judge_defaults["coach_enabled"])
                agent["judge"] = judge

            if agent.get("judge", {}).get("enabled") and not coach_guidance:
                agent["judge"]["enabled"] = False
                warnings.append(
                    {
                        "agent_type": agent_type,
                        "message": (
                            f"Coach disabled — no coach guidance configured for "
                            f"{agent_type}. Upload guidance in the admin page."
                        ),
                    }
                )

    if warnings:
        plan["warnings"] = warnings

    return plan


# ── Judge evaluation normalization and early exit ──


def normalize_evaluation(evaluation: dict, quality_threshold: float) -> tuple[dict, float, float]:
    """Recalculate scores with consistent float handling and ensure all fields present.

    Truncates the overall score to 2 decimal places (floor, not round) to prevent
    borderline scores from rounding up to meet the threshold.

    Args:
        evaluation: Raw evaluation dict from the judge model with scores_by_criterion.
        quality_threshold: Minimum overall score to pass quality check.

    Returns:
        Tuple of (normalized_evaluation, overall_score, raw_average):
        - normalized_evaluation: evaluation dict with recalculated fields
        - overall_score: truncated 2-decimal average
        - raw_average: untruncated average for logging
    """
    quality_threshold = float(quality_threshold)
    scores = evaluation.get("scores_by_criterion", {})
    completeness = float(scores.get("completeness", 0))
    specificity = float(scores.get("specificity", 0))
    actionability = float(scores.get("actionability", 0))
    # Truncate to 2 decimal places (floor) — never round UP to meet threshold
    raw_avg = (completeness + specificity + actionability) / 3.0
    overall = int(raw_avg * 100) / 100.0

    evaluation["overall_score"] = overall
    evaluation["scores_by_criterion"] = {
        "completeness": completeness,
        "specificity": specificity,
        "actionability": actionability,
    }
    evaluation["quality_met"] = overall >= quality_threshold
    evaluation.setdefault("critique", "")
    evaluation.setdefault("strengths", [])
    evaluation.setdefault("gaps", [])

    return evaluation, overall, raw_avg


def check_early_exit(
    evaluation: dict,
    overall: float,
    mode: str,
    iteration: int,
    prior_score: float,
    consecutive_drops: int,
) -> tuple[str, int]:
    """Detect score regression in coach mode and signal early exit.

    After 2 consecutive score drops, forces quality_met=True to stop the loop.
    This prevents infinite coaching cycles when the agent is getting worse.

    Args:
        evaluation: Normalized evaluation dict (mutated in place if early exit).
        overall: Current overall score.
        mode: 'evaluate' or 'coach'.
        iteration: Current iteration number (0-based).
        prior_score: Score from the previous iteration.
        consecutive_drops: Number of consecutive drops so far.

    Returns:
        Tuple of (early_exit_reason, updated_consecutive_drops):
        - early_exit_reason: 'score_declining' if exiting, '' otherwise
        - updated_consecutive_drops: updated count for next iteration
    """
    if mode != "coach" or evaluation["quality_met"]:
        return "", 0

    if iteration > 0 and prior_score > 0 and overall < prior_score:
        consecutive_drops += 1
    else:
        consecutive_drops = 0

    if consecutive_drops >= 2:
        evaluation["quality_met"] = True
        return "score_declining", consecutive_drops

    return "", consecutive_drops
