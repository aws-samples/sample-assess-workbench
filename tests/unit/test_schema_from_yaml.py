"""Validate that agent.yaml finding_schema blocks produce valid models.

This test loads the real YAML files and builds dynamic Pydantic models
from them, verifying the YAML-to-model pipeline end-to-end. It catches
typos, missing fields, and structural issues in the YAML that unit tests
with hardcoded dicts would miss.

Agents are discovered dynamically from agents/*/agent.yaml — no hardcoded
list to maintain. Only agents with a ``registry`` block (review agents)
are included.
"""

import pytest
import yaml
from pathlib import Path

from shared.schema_builder import build_finding_model, build_review_model, derive_severity


AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"


def _discover_review_agents() -> list[str]:
    """Discover all review agent directories that have a finding_schema."""
    agents = []
    for yaml_path in sorted(AGENTS_DIR.glob("*/agent.yaml")):
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        if cfg.get("registry", {}).get("finding_schema"):
            agents.append(yaml_path.parent.name)
    return agents


REVIEW_AGENTS = _discover_review_agents()


def _load_finding_schema(agent_dir_name: str) -> tuple[str, dict]:
    """Load finding_schema from an agent's agent.yaml.

    Returns:
        Tuple of (agent_type, finding_schema dict).
    """
    yaml_path = AGENTS_DIR / agent_dir_name / "agent.yaml"
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)
    agent_type = cfg["registry"]["agent_type"]
    schema = cfg["registry"]["finding_schema"]
    return agent_type, schema


class TestYamlSchemaLoading:
    """Every review agent's YAML produces a valid Pydantic model."""

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_builds_finding_model(self, agent_dir):
        agent_type, schema = _load_finding_schema(agent_dir)
        model = build_finding_model(agent_type, schema)
        assert model is not None
        assert "id" in model.model_fields
        assert "severity" in model.model_fields

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_builds_review_model(self, agent_dir):
        agent_type, schema = _load_finding_schema(agent_dir)
        model = build_review_model(agent_type, schema)
        assert "findings" in model.model_fields
        assert "summary" in model.model_fields

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_json_schema_is_valid(self, agent_dir):
        """The JSON schema (what the LLM sees) should be well-formed."""
        agent_type, schema = _load_finding_schema(agent_dir)
        model = build_review_model(agent_type, schema)
        json_schema = model.model_json_schema()
        assert "properties" in json_schema
        assert "findings" in json_schema["properties"]
        assert "summary" in json_schema["properties"]

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_primary_fields_exist_in_model(self, agent_dir):
        """Every field listed in primary_fields actually exists in the model."""
        agent_type, schema = _load_finding_schema(agent_dir)
        model = build_finding_model(agent_type, schema)
        for field_name in schema.get("primary_fields", []):
            assert field_name in model.model_fields, (
                f"{agent_dir}: primary_field '{field_name}' not in model"
            )

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_optional_fields_exist_in_model(self, agent_dir):
        """Every field listed in optional_fields actually exists in the model."""
        agent_type, schema = _load_finding_schema(agent_dir)
        model = build_finding_model(agent_type, schema)
        for field_name in schema.get("optional_fields", []):
            assert field_name in model.model_fields, (
                f"{agent_dir}: optional_field '{field_name}' not in model"
            )

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_display_hints_present_on_all_fields(self, agent_dir):
        """Every field in the schema has a display hint."""
        _, schema = _load_finding_schema(agent_dir)
        for field_name, field_def in schema.get("fields", {}).items():
            assert "display" in field_def, (
                f"{agent_dir}: field '{field_name}' missing 'display' hint"
            )


class TestDerivedSeverityAgents:
    """Agents with severity_source=derived have a complete matrix."""

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_derived_matrix_covers_all_combinations(self, agent_dir):
        """If severity is derived, every input enum combination has a mapping."""
        agent_type, schema = _load_finding_schema(agent_dir)
        if schema.get("severity_source") != "derived":
            pytest.skip(f"{agent_dir} uses direct severity")

        derivation = schema["severity_derivation"]
        fields = schema["fields"]
        valid_severities = set(schema["severity_levels"])

        # Build all combinations from input field enums
        import itertools

        input_enums = [fields[name]["enum"] for name in derivation["inputs"]]
        for combo in itertools.product(*input_enums):
            findings = [
                {name: val for name, val in zip(derivation["inputs"], combo)} | {"severity": ""}
            ]
            derive_severity(findings, schema)
            assert findings[0]["severity"] in valid_severities, (
                f"{agent_dir}: invalid severity for {combo}: {findings[0]['severity']}"
            )
