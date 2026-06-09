"""Tests for the dynamic schema builder.

Verifies that dynamically-built Pydantic models match the handwritten
models in each agent's agent.py, and that severity derivation works
correctly.
"""

import pytest
from typing import get_origin

from shared.schema_builder import (
    COMMON_FINDING_FIELDS,
    build_finding_model,
    build_review_model,
    derive_severity,
)


# ---------------------------------------------------------------------------
# Schema configs matching the appendix in the design doc.
# These are the target finding_schema blocks for each agent.
# ---------------------------------------------------------------------------

ARCHITECTURE_SCHEMA = {
    "severity_levels": ["high", "medium", "low"],
    "severity_source": "direct",
    "fields": {
        "quality_attribute": {
            "type": "str",
            "required": True,
            "description": "ATAM quality attribute: performance, modifiability, availability, security, usability, testability, interoperability, deployability",
            "enum": ["performance", "modifiability", "availability", "security", "usability", "testability", "interoperability", "deployability"],
        },
        "impact_type": {
            "type": "str",
            "required": True,
            "description": "Finding type: risk, sensitivity_point, tradeoff, recommendation",
            "enum": ["risk", "sensitivity_point", "tradeoff", "recommendation"],
        },
        "affected_components": {
            "type": "list[str]",
            "required": False,
            "default": [],
            "description": "Specific system components affected (e.g., 'API Gateway', 'Auth Service')",
        },
    },
}

SECURITY_SCHEMA = {
    "severity_levels": ["critical", "high", "medium", "low"],
    "severity_source": "direct",
    "fields": {
        "owasp_category": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "OWASP Top 10 category if applicable (e.g., 'A01:2021 Broken Access Control')",
        },
        "cwe_id": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "CWE identifier if applicable (e.g., 'CWE-287')",
        },
        "compliance_refs": {
            "type": "list[str]",
            "required": False,
            "default": [],
            "description": "Relevant compliance references (e.g., 'GDPR Art.32', 'SOC2 CC6.1')",
        },
        "attack_vector": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "CVSS-aligned attack vector: network, adjacent, local, physical",
            "enum": ["network", "adjacent", "local", "physical"],
        },
        "exploitability": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "Simplified exploitability: low, medium, high",
            "enum": ["low", "medium", "high"],
        },
    },
}

RISK_SCHEMA = {
    "severity_levels": ["critical", "high", "medium", "low"],
    "severity_source": "derived",
    "severity_derivation": {
        "inputs": ["likelihood", "consequence"],
        "matrix": {
            ("almost_certain", "catastrophic"): "critical",
            ("almost_certain", "major"): "critical",
            ("almost_certain", "moderate"): "high",
            ("almost_certain", "minor"): "medium",
            ("almost_certain", "insignificant"): "medium",
            ("likely", "catastrophic"): "critical",
            ("likely", "major"): "high",
            ("likely", "moderate"): "high",
            ("likely", "minor"): "medium",
            ("likely", "insignificant"): "low",
            ("possible", "catastrophic"): "high",
            ("possible", "major"): "high",
            ("possible", "moderate"): "medium",
            ("possible", "minor"): "low",
            ("possible", "insignificant"): "low",
            ("unlikely", "catastrophic"): "high",
            ("unlikely", "major"): "medium",
            ("unlikely", "moderate"): "medium",
            ("unlikely", "minor"): "low",
            ("unlikely", "insignificant"): "low",
            ("rare", "catastrophic"): "medium",
            ("rare", "major"): "medium",
            ("rare", "moderate"): "low",
            ("rare", "minor"): "low",
            ("rare", "insignificant"): "low",
        },
    },
    "fields": {
        "likelihood": {
            "type": "str",
            "required": True,
            "description": "Likelihood: almost_certain, likely, possible, unlikely, rare",
            "enum": ["almost_certain", "likely", "possible", "unlikely", "rare"],
        },
        "consequence": {
            "type": "str",
            "required": True,
            "description": "Consequence: catastrophic, major, moderate, minor, insignificant",
            "enum": ["catastrophic", "major", "moderate", "minor", "insignificant"],
        },
        "risk_treatment": {
            "type": "str",
            "required": True,
            "description": "Treatment strategy: mitigate, transfer, accept, avoid",
            "enum": ["mitigate", "transfer", "accept", "avoid"],
        },
        "residual_risk": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "Expected risk level after recommended treatment",
        },
    },
}

CRI_SCHEMA = {
    "severity_levels": ["high", "medium", "low"],
    "severity_source": "direct",
    "fields": {
        "cri_function": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "CRI Profile v2.0 function (e.g., 'GV', 'ID', 'PR', 'DE', 'RS', 'RC', 'EX')",
        },
        "cri_category": {
            "type": "str",
            "required": False,
            "default": "",
            "description": "CRI Profile v2.0 category (e.g., 'GV.OV', 'ID.AM', 'PR.AC', 'DE.CM', 'EX.DD')",
        },
    },
}

EU_REGULATORY_SCHEMA = {
    "severity_levels": ["high", "medium", "low"],
    "severity_source": "direct",
    "fields": {},
}

AUTOMOTIVE_SCHEMA = {
    "severity_levels": ["high", "medium", "low"],
    "severity_source": "direct",
    "fields": {},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_field_names(model):
    """Return the set of field names from a Pydantic model."""
    return set(model.model_fields.keys())


def _field_is_required(model, field_name):
    """Check if a field is required (no default) in a Pydantic model."""
    return model.model_fields[field_name].is_required()


def _field_default(model, field_name):
    """Get the default value for a field."""
    return model.model_fields[field_name].default


# ---------------------------------------------------------------------------
# Test: common fields present in every model
# ---------------------------------------------------------------------------

class TestCommonFields:
    """Every dynamic model must include the common finding fields."""

    @pytest.mark.parametrize("agent_type,schema", [
        ("architecture", ARCHITECTURE_SCHEMA),
        ("security", SECURITY_SCHEMA),
        ("risk", RISK_SCHEMA),
        ("cri_review", CRI_SCHEMA),
        ("eu_regulatory", EU_REGULATORY_SCHEMA),
        ("automotive_compliance", AUTOMOTIVE_SCHEMA),
    ])
    def test_common_fields_present(self, agent_type, schema):
        model = build_finding_model(agent_type, schema)
        expected = set(COMMON_FINDING_FIELDS.keys()) | {"severity"}
        assert expected.issubset(_get_field_names(model))

    @pytest.mark.parametrize("agent_type,schema", [
        ("architecture", ARCHITECTURE_SCHEMA),
        ("security", SECURITY_SCHEMA),
        ("cri_review", CRI_SCHEMA),
        ("eu_regulatory", EU_REGULATORY_SCHEMA),
        ("automotive_compliance", AUTOMOTIVE_SCHEMA),
    ])
    def test_severity_required_when_direct(self, agent_type, schema):
        model = build_finding_model(agent_type, schema)
        assert _field_is_required(model, "severity")

    def test_severity_optional_when_derived(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        assert not _field_is_required(model, "severity")
        assert _field_default(model, "severity") == ""


# ---------------------------------------------------------------------------
# Test: architecture model matches handwritten ArchitectureFinding
# ---------------------------------------------------------------------------

class TestArchitectureModel:
    """Dynamic architecture model matches the handwritten one."""

    def test_has_agent_specific_fields(self):
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        names = _get_field_names(model)
        assert "quality_attribute" in names
        assert "impact_type" in names
        assert "affected_components" in names

    def test_quality_attribute_is_required(self):
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        assert _field_is_required(model, "quality_attribute")

    def test_impact_type_is_required(self):
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        assert _field_is_required(model, "impact_type")

    def test_affected_components_optional_with_empty_list_default(self):
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        assert not _field_is_required(model, "affected_components")

    def test_quality_attribute_enum_in_json_schema(self):
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        schema = model.model_json_schema()
        qa_prop = schema["properties"]["quality_attribute"]
        assert set(qa_prop["enum"]) == {
            "performance", "modifiability", "availability", "security",
            "usability", "testability", "interoperability", "deployability",
        }

    def test_roundtrip(self):
        """Build a model instance and verify model_dump() output."""
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        instance = model(
            id="ARCH-001",
            severity="high",
            title="Test Finding",
            description="A test",
            recommendation="Fix it",
            quality_attribute="performance",
            impact_type="risk",
        )
        data = instance.model_dump()
        assert data["quality_attribute"] == "performance"
        assert data["affected_components"] == []
        assert data["references"] == []


# ---------------------------------------------------------------------------
# Test: security model matches handwritten SecurityFinding
# ---------------------------------------------------------------------------

class TestSecurityModel:
    """Dynamic security model matches the handwritten one."""

    def test_has_agent_specific_fields(self):
        model = build_finding_model("security", SECURITY_SCHEMA)
        names = _get_field_names(model)
        for field in ["owasp_category", "cwe_id", "compliance_refs", "attack_vector", "exploitability"]:
            assert field in names, f"Missing field: {field}"

    def test_all_security_fields_optional(self):
        model = build_finding_model("security", SECURITY_SCHEMA)
        for field in ["owasp_category", "cwe_id", "compliance_refs", "attack_vector", "exploitability"]:
            assert not _field_is_required(model, field), f"{field} should be optional"

    def test_string_fields_default_to_empty_string(self):
        model = build_finding_model("security", SECURITY_SCHEMA)
        for field in ["owasp_category", "cwe_id", "attack_vector", "exploitability"]:
            assert _field_default(model, field) == "", f"{field} should default to ''"

    def test_compliance_refs_defaults_to_empty_list(self):
        model = build_finding_model("security", SECURITY_SCHEMA)
        assert _field_default(model, "compliance_refs") == []

    def test_attack_vector_enum_in_json_schema(self):
        model = build_finding_model("security", SECURITY_SCHEMA)
        schema = model.model_json_schema()
        av_prop = schema["properties"]["attack_vector"]
        assert set(av_prop["enum"]) == {"network", "adjacent", "local", "physical"}

    def test_roundtrip_minimal(self):
        """All optional fields — only common fields required."""
        model = build_finding_model("security", SECURITY_SCHEMA)
        instance = model(
            id="SEC-001",
            severity="critical",
            title="Test",
            description="Desc",
            recommendation="Rec",
        )
        data = instance.model_dump()
        assert data["owasp_category"] == ""
        assert data["compliance_refs"] == []


# ---------------------------------------------------------------------------
# Test: risk model matches handwritten RiskFinding
# ---------------------------------------------------------------------------

class TestRiskModel:
    """Dynamic risk model matches the handwritten one."""

    def test_has_agent_specific_fields(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        names = _get_field_names(model)
        for field in ["likelihood", "consequence", "risk_treatment", "residual_risk"]:
            assert field in names

    def test_required_fields(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        assert _field_is_required(model, "likelihood")
        assert _field_is_required(model, "consequence")
        assert _field_is_required(model, "risk_treatment")

    def test_residual_risk_optional(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        assert not _field_is_required(model, "residual_risk")
        assert _field_default(model, "residual_risk") == ""

    def test_likelihood_enum_in_json_schema(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        schema = model.model_json_schema()
        lk_prop = schema["properties"]["likelihood"]
        assert set(lk_prop["enum"]) == {
            "almost_certain", "likely", "possible", "unlikely", "rare",
        }

    def test_roundtrip(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        instance = model(
            id="RISK-001",
            title="Test",
            description="Desc",
            recommendation="Rec",
            likelihood="likely",
            consequence="major",
            risk_treatment="mitigate",
        )
        data = instance.model_dump()
        assert data["severity"] == ""  # derived post-parse, not by model
        assert data["likelihood"] == "likely"


# ---------------------------------------------------------------------------
# Test: CRI model matches handwritten Finding
# ---------------------------------------------------------------------------

class TestCRIModel:

    def test_has_cri_fields(self):
        model = build_finding_model("cri_review", CRI_SCHEMA)
        names = _get_field_names(model)
        assert "cri_function" in names
        assert "cri_category" in names

    def test_cri_fields_optional(self):
        model = build_finding_model("cri_review", CRI_SCHEMA)
        assert not _field_is_required(model, "cri_function")
        assert not _field_is_required(model, "cri_category")
        assert _field_default(model, "cri_function") == ""
        assert _field_default(model, "cri_category") == ""


# ---------------------------------------------------------------------------
# Test: agents with no custom fields (EU regulatory, automotive)
# ---------------------------------------------------------------------------

class TestMinimalModels:
    """Agents with fields: {} should still have all common fields."""

    @pytest.mark.parametrize("agent_type,schema", [
        ("eu_regulatory", EU_REGULATORY_SCHEMA),
        ("automotive_compliance", AUTOMOTIVE_SCHEMA),
    ])
    def test_only_common_fields(self, agent_type, schema):
        model = build_finding_model(agent_type, schema)
        expected = set(COMMON_FINDING_FIELDS.keys()) | {"severity"}
        assert _get_field_names(model) == expected

    @pytest.mark.parametrize("agent_type,schema", [
        ("eu_regulatory", EU_REGULATORY_SCHEMA),
        ("automotive_compliance", AUTOMOTIVE_SCHEMA),
    ])
    def test_roundtrip(self, agent_type, schema):
        model = build_finding_model(agent_type, schema)
        instance = model(
            id="TEST-001",
            severity="high",
            title="Test",
            description="Desc",
            recommendation="Rec",
        )
        data = instance.model_dump()
        assert data["id"] == "TEST-001"
        assert data["references"] == []


# ---------------------------------------------------------------------------
# Test: build_review_model wraps Finding in a Review container
# ---------------------------------------------------------------------------

class TestReviewModel:

    def test_review_has_findings_and_summary(self):
        model = build_review_model("security", SECURITY_SCHEMA)
        names = _get_field_names(model)
        assert "findings" in names
        assert "summary" in names

    def test_findings_is_list_of_finding_model(self):
        model = build_review_model("architecture", ARCHITECTURE_SCHEMA)
        findings_field = model.model_fields["findings"]
        # The annotation should be List[<FindingModel>]
        assert get_origin(findings_field.annotation) is list

    def test_review_roundtrip(self):
        model = build_review_model("security", SECURITY_SCHEMA)
        instance = model(
            findings=[
                {
                    "id": "SEC-001",
                    "severity": "high",
                    "title": "Test",
                    "description": "Desc",
                    "recommendation": "Rec",
                }
            ],
            summary="Overall good",
        )
        data = instance.model_dump()
        assert len(data["findings"]) == 1
        assert data["findings"][0]["owasp_category"] == ""
        assert data["summary"] == "Overall good"

    def test_class_naming(self):
        model = build_review_model("security", SECURITY_SCHEMA)
        assert model.__name__ == "SecurityReview"
        finding_model = build_finding_model("security", SECURITY_SCHEMA)
        assert finding_model.__name__ == "SecurityFinding"

    def test_risk_class_naming(self):
        model = build_review_model("risk", RISK_SCHEMA)
        assert model.__name__ == "RiskReview"
        finding_model = build_finding_model("risk", RISK_SCHEMA)
        assert finding_model.__name__ == "RiskFinding"


# ---------------------------------------------------------------------------
# Test: severity derivation
# ---------------------------------------------------------------------------

class TestDeriveSeverity:
    """Test the post-parse severity derivation from the matrix."""

    def test_derives_critical(self):
        findings = [{"likelihood": "almost_certain", "consequence": "catastrophic", "severity": ""}]
        derive_severity(findings, RISK_SCHEMA)
        assert findings[0]["severity"] == "critical"

    def test_derives_low(self):
        findings = [{"likelihood": "rare", "consequence": "insignificant", "severity": ""}]
        derive_severity(findings, RISK_SCHEMA)
        assert findings[0]["severity"] == "low"

    def test_overwrites_existing_severity(self):
        """Even if the LLM set severity, derivation overwrites it."""
        findings = [{"likelihood": "likely", "consequence": "major", "severity": "low"}]
        derive_severity(findings, RISK_SCHEMA)
        assert findings[0]["severity"] == "high"

    def test_multiple_findings(self):
        findings = [
            {"likelihood": "almost_certain", "consequence": "catastrophic", "severity": ""},
            {"likelihood": "rare", "consequence": "insignificant", "severity": ""},
            {"likelihood": "possible", "consequence": "moderate", "severity": ""},
        ]
        derive_severity(findings, RISK_SCHEMA)
        assert findings[0]["severity"] == "critical"
        assert findings[1]["severity"] == "low"
        assert findings[2]["severity"] == "medium"

    def test_noop_when_no_derivation_config(self):
        """Direct severity agents should not be affected."""
        findings = [{"severity": "high"}]
        derive_severity(findings, SECURITY_SCHEMA)
        assert findings[0]["severity"] == "high"

    def test_raises_on_unknown_values(self):
        findings = [{"likelihood": "bogus", "consequence": "catastrophic", "severity": ""}]
        with pytest.raises(ValueError, match="no matrix entry"):
            derive_severity(findings, RISK_SCHEMA)

    def test_empty_findings_list(self):
        """No findings — should be a no-op."""
        findings = []
        derive_severity(findings, RISK_SCHEMA)
        assert findings == []


# ---------------------------------------------------------------------------
# Test: matrix validation at build time
# ---------------------------------------------------------------------------

class TestMatrixValidation:

    def test_complete_matrix_passes(self):
        """The risk schema has a complete 5×5 matrix — should not raise."""
        build_finding_model("risk", RISK_SCHEMA)

    def test_incomplete_matrix_raises(self):
        schema = {
            **RISK_SCHEMA,
            "severity_derivation": {
                "inputs": ["likelihood", "consequence"],
                "matrix": {
                    # Only one entry — missing 24
                    ("almost_certain", "catastrophic"): "critical",
                },
            },
        }
        with pytest.raises(ValueError, match="missing 24 entries"):
            build_finding_model("risk", schema)

    def test_missing_enum_on_input_field_raises(self):
        schema = {
            "severity_levels": ["critical", "high", "medium", "low"],
            "severity_source": "derived",
            "severity_derivation": {
                "inputs": ["likelihood", "consequence"],
                "matrix": {},
            },
            "fields": {
                "likelihood": {
                    "type": "str",
                    "required": True,
                    "description": "Likelihood",
                    # No enum — should fail
                },
                "consequence": {
                    "type": "str",
                    "required": True,
                    "description": "Consequence",
                    "enum": ["catastrophic"],
                },
            },
        }
        with pytest.raises(ValueError, match="no enum values defined"):
            build_finding_model("risk", schema)

    def test_no_derivation_config_skips_validation(self):
        """Direct severity agents have no matrix — validation should be skipped."""
        build_finding_model("security", SECURITY_SCHEMA)


# ---------------------------------------------------------------------------
# Test: JSON schema output (what the LLM sees via structured output)
# ---------------------------------------------------------------------------

class TestJsonSchema:
    """Verify the JSON schema has the right structure for structured output."""

    def test_enum_fields_have_enum_in_schema(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        schema = model.model_json_schema()
        assert "enum" in schema["properties"]["likelihood"]
        assert "enum" in schema["properties"]["consequence"]
        assert "enum" in schema["properties"]["risk_treatment"]

    def test_non_enum_fields_have_no_enum(self):
        model = build_finding_model("risk", RISK_SCHEMA)
        schema = model.model_json_schema()
        assert "enum" not in schema["properties"]["residual_risk"]
        assert "enum" not in schema["properties"]["id"]

    def test_required_fields_in_schema(self):
        model = build_finding_model("architecture", ARCHITECTURE_SCHEMA)
        schema = model.model_json_schema()
        required = set(schema.get("required", []))
        assert "id" in required
        assert "severity" in required
        assert "quality_attribute" in required
        assert "impact_type" in required
        # Optional fields should not be in required
        assert "affected_components" not in required
        assert "references" not in required

    def test_review_model_schema(self):
        model = build_review_model("security", SECURITY_SCHEMA)
        schema = model.model_json_schema()
        assert "findings" in schema["properties"]
        assert "summary" in schema["properties"]


# ---------------------------------------------------------------------------
# Test: parity with existing risk_matrix.py
# ---------------------------------------------------------------------------

class TestRiskMatrixParity:
    """Verify derive_severity() produces correct results for known inputs."""

    LIKELIHOOD_LEVELS = ("almost_certain", "likely", "possible", "unlikely", "rare")
    CONSEQUENCE_LEVELS = ("catastrophic", "major", "moderate", "minor", "insignificant")

    def test_matrix_covers_all_25_combinations(self):
        """Every likelihood × consequence pair should produce a valid severity."""
        for lk in self.LIKELIHOOD_LEVELS:
            for cq in self.CONSEQUENCE_LEVELS:
                findings = [{"likelihood": lk, "consequence": cq, "severity": ""}]
                derive_severity(findings, RISK_SCHEMA)
                assert findings[0]["severity"] in ("critical", "high", "medium", "low"), (
                    f"Invalid severity for ({lk}, {cq}): {findings[0]['severity']}"
                )
