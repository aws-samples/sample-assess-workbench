"""Verify that finding_schema survives the seed script's JSON serialization.

The seed_agent_registry.sh script does:
    json.dumps(reg['finding_schema'])

...to store the schema as a JSON string in DynamoDB. This test simulates
that exact path: YAML → dict → JSON string → dict → build_finding_model().
It catches any YAML constructs that don't survive JSON round-tripping
(e.g., tuples become lists, sets become lists, etc.).

Agents are discovered dynamically from agents/*/agent.yaml — no hardcoded
list to maintain.
"""

import json
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


def _yaml_to_json_roundtrip(agent_dir_name: str) -> tuple[str, dict]:
    """Simulate the seed script's serialization path.

    YAML → yaml.safe_load → json.dumps → json.loads → dict

    This is exactly what happens when the seed script writes to DynamoDB
    and the generic runtime reads it back.

    Returns:
        Tuple of (agent_type, finding_schema dict after JSON round-trip).
    """
    yaml_path = AGENTS_DIR / agent_dir_name / "agent.yaml"
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f)

    reg = cfg["registry"]
    agent_type = reg["agent_type"]
    schema = reg["finding_schema"]

    # Simulate: seed script does json.dumps, DynamoDB stores as string,
    # generic runtime does json.loads
    json_str = json.dumps(schema)
    restored = json.loads(json_str)

    return agent_type, restored


class TestJsonRoundTrip:
    """finding_schema survives JSON serialization for all agents."""

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_builds_finding_model_after_roundtrip(self, agent_dir):
        agent_type, schema = _yaml_to_json_roundtrip(agent_dir)
        model = build_finding_model(agent_type, schema)
        assert "id" in model.model_fields
        assert "severity" in model.model_fields

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_builds_review_model_after_roundtrip(self, agent_dir):
        agent_type, schema = _yaml_to_json_roundtrip(agent_dir)
        model = build_review_model(agent_type, schema)
        assert "findings" in model.model_fields
        assert "summary" in model.model_fields

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_json_size_under_400kb(self, agent_dir):
        """DynamoDB item size limit is 400KB. The finding_schema JSON
        is one field in the item — verify it's not unreasonably large."""
        yaml_path = AGENTS_DIR / agent_dir / "agent.yaml"
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        json_str = json.dumps(cfg["registry"]["finding_schema"])
        assert len(json_str) < 10_000, f"{agent_dir} finding_schema JSON is {len(json_str)} bytes"

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_display_hints_survive_roundtrip(self, agent_dir):
        """display and color hints are preserved through JSON serialization."""
        _, schema = _yaml_to_json_roundtrip(agent_dir)
        for field_name, field_def in schema.get("fields", {}).items():
            assert "display" in field_def, (
                f"{agent_dir}: field '{field_name}' lost 'display' hint after JSON round-trip"
            )


class TestDerivedSeverityRoundTrip:
    """Severity derivation matrices survive JSON serialization."""

    @pytest.mark.parametrize("agent_dir", REVIEW_AGENTS)
    def test_derive_severity_after_roundtrip(self, agent_dir):
        agent_type, schema = _yaml_to_json_roundtrip(agent_dir)
        if schema.get("severity_source") != "derived":
            pytest.skip(f"{agent_dir} uses direct severity")

        import itertools

        derivation = schema["severity_derivation"]
        fields = schema["fields"]
        valid_severities = set(schema["severity_levels"])

        input_enums = [fields[name]["enum"] for name in derivation["inputs"]]
        for combo in itertools.product(*input_enums):
            findings = [
                {name: val for name, val in zip(derivation["inputs"], combo)} | {"severity": ""}
            ]
            derive_severity(findings, schema)
            assert findings[0]["severity"] in valid_severities, (
                f"{agent_dir}: invalid severity for {combo} after round-trip"
            )
