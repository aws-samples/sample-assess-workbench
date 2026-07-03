"""Unit tests for the markdown report renderer.

Source: api/core/report_renderer.py
Tests the pure render function that converts review findings into a
human-readable markdown report. No AWS dependencies.
"""

from core.report_renderer import render_markdown_report


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_summary(critical=0, high=0, medium=0, low=0):
    total = critical + high + medium + low
    return {
        "total_findings": total,
        "critical_severity": critical,
        "high_severity": high,
        "medium_severity": medium,
        "low_severity": low,
        "by_agent": {},
    }


def _make_finding(severity="high", title="Test Finding", **kwargs):
    base = {
        "id": kwargs.pop("id", "F1"),
        "severity": severity,
        "title": title,
        "description": kwargs.pop("description", "A test description."),
        "recommendation": kwargs.pop("recommendation", "Fix it."),
    }
    base.update(kwargs)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Basic structure
# ═══════════════════════════════════════════════════════════════════════════


class TestBasicStructure:
    def test_title_and_timestamp(self):
        md = render_markdown_report(
            reviews={},
            summary=_make_summary(),
            project_name="My Project",
            created_at="2025-01-15T10:00:00Z",
        )
        assert "# Review Report: My Project" in md
        assert "*Generated: 2025-01-15T10:00:00Z*" in md

    def test_executive_summary_table(self):
        md = render_markdown_report(
            reviews={},
            summary=_make_summary(critical=1, high=2, medium=3, low=4),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "| Critical | 1 |" in md
        assert "| High     | 2 |" in md
        assert "| Medium   | 3 |" in md
        assert "| Low      | 4 |" in md
        assert "| **Total** | **10** |" in md

    def test_empty_reviews_produces_valid_markdown(self):
        md = render_markdown_report(
            reviews={},
            summary=_make_summary(),
            project_name="Empty",
            created_at="2025-01-01",
        )
        assert "# Review Report: Empty" in md
        assert "## Consolidated Action Items" not in md

    def test_agent_summary_line(self):
        reviews = {
            "security": {"findings": [_make_finding()], "status": "completed"},
            "risk": {"findings": [], "status": "completed"},
        }
        summary = _make_summary(high=1)
        summary["by_agent"] = {"security": 1, "risk": 0}
        md = render_markdown_report(
            reviews=reviews,
            summary=summary,
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Risk (0 findings)" in md
        assert "Security (1 findings)" in md


# ═══════════════════════════════════════════════════════════════════════════
# Agent ordering
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentOrdering:
    def test_alphabetical_without_plan(self):
        reviews = {
            "risk": {"findings": [], "status": "completed"},
            "architecture": {"findings": [], "status": "completed"},
            "security": {"findings": [], "status": "completed"},
        }
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(),
            project_name="Test",
            created_at="2025-01-01",
        )
        arch_pos = md.index("## Architecture Review")
        risk_pos = md.index("## Risk Review")
        sec_pos = md.index("## Security Review")
        assert arch_pos < risk_pos < sec_pos

    def test_plan_group_order_with_alpha_within_group(self):
        reviews = {
            "risk": {"findings": [], "status": "completed"},
            "architecture": {"findings": [], "status": "completed"},
            "security": {"findings": [], "status": "completed"},
        }
        plan = {
            "groups": [
                {
                    "agents": [
                        {"agent_type": "security"},
                        {"agent_type": "architecture"},
                    ]
                },
                {
                    "agents": [
                        {"agent_type": "risk"},
                    ]
                },
            ],
        }
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(),
            project_name="Test",
            created_at="2025-01-01",
            plan=plan,
        )
        # Group 1: architecture, security (alpha within group)
        # Group 2: risk
        arch_pos = md.index("## Architecture Review")
        sec_pos = md.index("## Security Review")
        risk_pos = md.index("## Risk Review")
        assert arch_pos < sec_pos < risk_pos

    def test_agents_not_in_plan_appended_alphabetically(self):
        reviews = {
            "security": {"findings": [], "status": "completed"},
            "cri": {"findings": [], "status": "completed"},
        }
        plan = {"groups": [{"agents": [{"agent_type": "security"}]}]}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(),
            project_name="Test",
            created_at="2025-01-01",
            plan=plan,
        )
        sec_pos = md.index("## Security Review")
        cri_pos = md.index("## Cri Review")
        assert sec_pos < cri_pos


# ═══════════════════════════════════════════════════════════════════════════
# Severity sorting within agent sections
# ═══════════════════════════════════════════════════════════════════════════


class TestSeveritySorting:
    def test_findings_sorted_by_severity(self):
        reviews = {
            "security": {
                "findings": [
                    _make_finding(severity="low", title="Low Issue"),
                    _make_finding(severity="critical", title="Critical Issue"),
                    _make_finding(severity="high", title="High Issue"),
                ],
                "status": "completed",
            },
        }
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(critical=1, high=1, low=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        crit_pos = md.index("[CRITICAL] Critical Issue")
        high_pos = md.index("[HIGH] High Issue")
        low_pos = md.index("[LOW] Low Issue")
        assert crit_pos < high_pos < low_pos


# ═══════════════════════════════════════════════════════════════════════════
# Agent-specific enrichment
# ═══════════════════════════════════════════════════════════════════════════


class TestSecurityEnrichment:
    def test_owasp_and_cwe_rendered(self):
        finding = _make_finding(
            owasp_category="A01:2021 Broken Access Control",
            cwe_id="CWE-287",
        )
        reviews = {"security": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "OWASP: A01:2021 Broken Access Control" in md
        assert "CWE: CWE-287" in md

    def test_compliance_refs_rendered(self):
        finding = _make_finding(compliance_refs=["GDPR Art.32", "CPS 234 s14"])
        reviews = {"security": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Compliance: GDPR Art.32, CPS 234 s14" in md

    def test_empty_enrichment_fields_omitted(self):
        finding = _make_finding(owasp_category="", cwe_id="", compliance_refs=[])
        reviews = {"security": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "OWASP:" not in md
        assert "CWE:" not in md
        assert "Compliance:" not in md


class TestArchitectureEnrichment:
    def test_quality_attribute_and_impact(self):
        finding = _make_finding(
            quality_attribute="performance",
            impact_type="tradeoff",
        )
        reviews = {"architecture": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Quality Attribute: performance" in md
        assert "Impact: tradeoff" in md

    def test_affected_components(self):
        finding = _make_finding(affected_components=["API Gateway", "Auth Service"])
        reviews = {"architecture": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Components: API Gateway, Auth Service" in md


class TestRiskEnrichment:
    def test_likelihood_consequence_treatment(self):
        finding = _make_finding(
            likelihood="likely",
            consequence="major",
            risk_treatment="mitigate",
        )
        reviews = {"risk": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Likelihood: likely" in md
        assert "Consequence: major" in md
        assert "Treatment: mitigate" in md

    def test_residual_risk_when_present(self):
        finding = _make_finding(
            likelihood="likely",
            consequence="major",
            risk_treatment="mitigate",
            residual_risk="low",
        )
        reviews = {"risk": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Residual Risk: low" in md

    def test_residual_risk_omitted_when_empty(self):
        finding = _make_finding(
            likelihood="likely",
            consequence="major",
            risk_treatment="mitigate",
            residual_risk="",
        )
        reviews = {"risk": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "Residual Risk" not in md


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_failed_agent_shows_status(self):
        reviews = {
            "security": {
                "findings": [],
                "status": "failed",
                "status_reason": "Model timeout",
            },
        }
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "*Agent status: failed*" in md
        assert "*Reason: Model timeout*" in md
        # No findings section for failed agents.
        assert "### [" not in md

    def test_finding_missing_optional_fields(self):
        """Findings with only required fields should render without errors."""
        finding = {
            "id": "X1",
            "severity": "medium",
            "title": "Bare Finding",
            "description": "",
            "recommendation": "",
        }
        reviews = {"security": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(medium=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "[MEDIUM] Bare Finding" in md

    def test_unknown_agent_type_renders_extra_fields(self):
        """Agent types we don't have specific enrichment for should still
        render non-common fields as key: value pairs."""
        finding = _make_finding(custom_field="custom_value")
        reviews = {"compliance": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "custom_field: custom_value" in md


# ═══════════════════════════════════════════════════════════════════════════
# Consolidated action items
# ═══════════════════════════════════════════════════════════════════════════


class TestConsolidatedActionItems:
    def test_action_items_sorted_by_severity(self):
        reviews = {
            "security": {
                "findings": [_make_finding(severity="medium", title="Med")],
                "status": "completed",
            },
            "risk": {
                "findings": [_make_finding(severity="critical", title="Crit")],
                "status": "completed",
            },
        }
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(critical=1, medium=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "## Consolidated Action Items" in md
        # F-001 should be the critical finding.
        assert "| F-001 | CRITICAL | Risk | Crit |" in md
        assert "| F-002 | MEDIUM | Security | Med |" in md

    def test_sequential_ids(self):
        findings = [_make_finding(severity="high", title=f"Issue {i}") for i in range(3)]
        reviews = {"security": {"findings": findings, "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=3),
            project_name="Test",
            created_at="2025-01-01",
        )
        assert "F-001" in md
        assert "F-002" in md
        assert "F-003" in md

    def test_long_recommendation_truncated(self):
        long_rec = "A" * 200
        finding = _make_finding(recommendation=long_rec)
        reviews = {"security": {"findings": [finding], "status": "completed"}}
        md = render_markdown_report(
            reviews=reviews,
            summary=_make_summary(high=1),
            project_name="Test",
            created_at="2025-01-01",
        )
        # The action items table should truncate.
        lines = [line for line in md.split("\n") if "F-001" in line]
        assert len(lines) == 1
        assert lines[0].endswith("... |")
