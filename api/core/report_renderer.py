"""Markdown report renderer for review findings.

Pure function — no AWS dependencies, fully testable. Takes the same data
structures that ``aggregate_results`` writes to ``findings.json`` in S3
and produces a human-readable markdown report.
"""

from __future__ import annotations

from typing import Any


# Severity ordering for sorting findings (highest first).
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def render_markdown_report(
    reviews: dict[str, Any],
    summary: dict[str, Any],
    project_name: str,
    created_at: str,
    plan: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> str:
    """Render a markdown report from review findings.

    Args:
        reviews: Dict keyed by agent_type, each value has ``findings``,
            ``summary``, ``status``, ``status_reason``.
        summary: Severity counts from ``compute_summary()``.
        project_name: Human-readable project name.
        created_at: ISO-8601 timestamp of the review.
        plan: Optional review plan dict (used to determine agent ordering
            from groups). When absent, agents are sorted alphabetically.
        metrics: Optional metrics dict (currently unused, reserved for
            future enrichment such as token counts or durations).

    Returns:
        Complete markdown report as a string.
    """
    parts: list[str] = []

    # -- Title --
    parts.append(f"# Review Report: {project_name}")
    parts.append(f"*Generated: {created_at}*")
    parts.append("")

    # -- Executive Summary --
    parts.append("## Executive Summary")
    parts.append("")
    parts.append("| Severity | Count |")
    parts.append("|----------|-------|")
    parts.append(f"| Critical | {summary.get('critical_severity', 0)} |")
    parts.append(f"| High     | {summary.get('high_severity', 0)} |")
    parts.append(f"| Medium   | {summary.get('medium_severity', 0)} |")
    parts.append(f"| Low      | {summary.get('low_severity', 0)} |")
    total = summary.get("total_findings", 0)
    parts.append(f"| **Total** | **{total}** |")
    parts.append("")

    # Agent summary line: "Security (N findings), Architecture (N findings)"
    agent_order = _resolve_agent_order(reviews, plan)
    by_agent = summary.get("by_agent", {})
    agent_parts = []
    for agent_type in agent_order:
        count = by_agent.get(agent_type, len(reviews.get(agent_type, {}).get("findings", [])))
        agent_parts.append(f"{_display_name(agent_type)} ({count} findings)")
    if agent_parts:
        parts.append(f"**Agents:** {', '.join(agent_parts)}")
        parts.append("")

    # -- Per-agent sections --
    # Track all findings for the consolidated action items table.
    all_findings: list[tuple[str, dict]] = []

    for agent_type in agent_order:
        review_data = reviews[agent_type]
        status = review_data.get("status", "completed")
        findings = review_data.get("findings", [])

        display = _display_name(agent_type)
        parts.append(f"## {display} Review")

        if status != "completed":
            reason = review_data.get("status_reason", "")
            parts.append(f"*Agent status: {status}*")
            if reason:
                parts.append(f"*Reason: {reason}*")
            parts.append("")
            continue

        parts.append(f"*{len(findings)} findings*")
        parts.append("")

        sorted_findings = sorted(
            findings,
            key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "").lower(), 99),
        )

        for finding in sorted_findings:
            all_findings.append((agent_type, finding))
            _render_finding(parts, finding, agent_type)

    # -- Consolidated Action Items --
    if all_findings:
        _render_action_items(parts, all_findings)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_agent_order(
    reviews: dict[str, Any],
    plan: dict[str, Any] | None,
) -> list[str]:
    """Determine agent display order from the plan's groups.

    Agents appear in the order their groups are defined in the plan,
    sorted alphabetically within each group. Agents present in reviews
    but missing from the plan are appended alphabetically at the end.
    """
    if not plan or "groups" not in plan:
        return sorted(reviews.keys())

    ordered: list[str] = []
    for group in plan.get("groups", []):
        group_agents = []
        for agent_cfg in group.get("agents", []):
            at = agent_cfg.get("agent_type", "")
            if at in reviews and at not in ordered:
                group_agents.append(at)
        ordered.extend(sorted(group_agents))

    # Append any agents not in the plan (alphabetically).
    for at in sorted(reviews.keys()):
        if at not in ordered:
            ordered.append(at)

    return ordered


def _display_name(agent_type: str) -> str:
    """Convert an agent_type slug to a display name.

    ``'security'`` → ``'Security'``, ``'eu_regulatory'`` → ``'Eu Regulatory'``.
    """
    return agent_type.replace("_", " ").title()


def _render_finding(parts: list[str], finding: dict, agent_type: str) -> None:
    """Render a single finding as a markdown section."""
    severity = finding.get("severity", "unknown").upper()
    title = finding.get("title", "Untitled Finding")
    parts.append(f"### [{severity}] {title}")

    description = finding.get("description", "")
    if description:
        parts.append(description)
        parts.append("")

    recommendation = finding.get("recommendation", "")
    if recommendation:
        parts.append(f"**Recommendation:** {recommendation}")
        parts.append("")

    # Agent-specific enrichment metadata line.
    meta = _build_enrichment_line(finding, agent_type)
    if meta:
        parts.append(f"*{meta}*")
        parts.append("")


def _build_enrichment_line(finding: dict, agent_type: str) -> str:
    """Build the italicised metadata line below a finding.

    Returns an empty string when there's nothing to show.
    """
    segments: list[str] = []

    if agent_type == "security":
        owasp = finding.get("owasp_category", "")
        if owasp:
            segments.append(f"OWASP: {owasp}")
        cwe = finding.get("cwe_id", "")
        if cwe:
            segments.append(f"CWE: {cwe}")
        refs = finding.get("compliance_refs", [])
        if refs:
            segments.append(f"Compliance: {', '.join(refs)}")
        vector = finding.get("attack_vector", "")
        if vector:
            segments.append(f"Attack Vector: {vector}")

    elif agent_type == "architecture":
        qa = finding.get("quality_attribute", "")
        if qa:
            segments.append(f"Quality Attribute: {qa}")
        impact = finding.get("impact_type", "")
        if impact:
            segments.append(f"Impact: {impact}")
        components = finding.get("affected_components", [])
        if components:
            segments.append(f"Components: {', '.join(components)}")

    elif agent_type == "risk":
        likelihood = finding.get("likelihood", "")
        if likelihood:
            segments.append(f"Likelihood: {likelihood}")
        consequence = finding.get("consequence", "")
        if consequence:
            segments.append(f"Consequence: {consequence}")
        treatment = finding.get("risk_treatment", "")
        if treatment:
            segments.append(f"Treatment: {treatment}")
        residual = finding.get("residual_risk", "")
        if residual:
            segments.append(f"Residual Risk: {residual}")

    elif agent_type == "au_fsi_compliance":
        reg_ref = finding.get("regulatory_reference", "")
        if reg_ref:
            segments.append(f"Regulation: {reg_ref}")
        obligation = finding.get("obligation_type", "")
        if obligation:
            segments.append(f"Obligation: {obligation}")
        gap = finding.get("compliance_gap", "")
        if gap:
            segments.append(f"Gap: {gap}")
        authority = finding.get("authority_level", "")
        if authority:
            segments.append(f"Authority: {authority}")
        timeframe = finding.get("remediation_timeframe", "")
        if timeframe:
            segments.append(f"Remediation: {timeframe}")

    else:
        # Unknown agent type — render any non-common fields as key: value.
        common = {"id", "severity", "title", "description", "recommendation", "references"}
        for key, value in finding.items():
            if key in common or not value:
                continue
            if isinstance(value, list):
                segments.append(f"{key}: {', '.join(str(v) for v in value)}")
            else:
                segments.append(f"{key}: {value}")

    return " | ".join(segments)


def _render_action_items(
    parts: list[str],
    all_findings: list[tuple[str, dict]],
) -> None:
    """Render the consolidated action items table sorted by severity."""
    # Sort by severity (highest first), preserving per-agent order as tiebreaker.
    sorted_items = sorted(
        all_findings,
        key=lambda item: _SEVERITY_ORDER.get(
            item[1].get("severity", "").lower(),
            99,
        ),
    )

    parts.append("## Consolidated Action Items")
    parts.append("")
    parts.append("| ID | Severity | Agent | Finding | Recommendation |")
    parts.append("|----|----------|-------|---------|----------------|")

    for idx, (agent_type, finding) in enumerate(sorted_items, start=1):
        fid = f"F-{idx:03d}"
        severity = finding.get("severity", "unknown").upper()
        agent = _display_name(agent_type)
        title = finding.get("title", "Untitled")
        rec = finding.get("recommendation", "")
        # Truncate long recommendations for the table.
        if len(rec) > 120:
            rec = rec[:117] + "..."
        parts.append(f"| {fid} | {severity} | {agent} | {title} | {rec} |")

    parts.append("")
