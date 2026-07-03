"""Unit tests for pure logic extracted from workflow Lambdas.

Sources:
  - api/core/plan_validation.py → build_plan_tool
  - api/core/dynamodb.py → convert_floats_to_decimal
"""

from decimal import Decimal
from core.plan_validation import build_plan_tool
from core.dynamodb import convert_floats_to_decimal

# ═══════════════════════════════════════════════════════════════════════════
# build_plan_tool (plan_validation.py)
#
# Builds the Bedrock Converse tool schema dynamically from available agent
# types. The agent_types list controls the enum values in the schema.
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildPlanTool:
    """The tool schema must reflect the available agent types so the LLM
    can only select valid agents."""

    def test_agent_types_appear_in_enum(self):
        agents = ["architecture", "security", "risk"]
        tool = build_plan_tool(agents)
        schema = tool["toolSpec"]["inputSchema"]["json"]
        agent_items = schema["properties"]["groups"]["items"]["properties"]["agents"]["items"]
        assert agent_items["properties"]["agent_type"]["enum"] == agents

    def test_tool_name_is_create_review_plan(self):
        tool = build_plan_tool(["architecture"])
        assert tool["toolSpec"]["name"] == "create_review_plan"

    def test_required_fields(self):
        tool = build_plan_tool(["architecture"])
        required = tool["toolSpec"]["inputSchema"]["json"]["required"]
        assert set(required) == {"document_type", "complexity", "rationale", "groups"}

    def test_empty_agent_list_produces_empty_enum(self):
        tool = build_plan_tool([])
        schema = tool["toolSpec"]["inputSchema"]["json"]
        agent_items = schema["properties"]["groups"]["items"]["properties"]["agents"]["items"]
        assert agent_items["properties"]["agent_type"]["enum"] == []

    def test_single_agent(self):
        tool = build_plan_tool(["automotive_compliance"])
        schema = tool["toolSpec"]["inputSchema"]["json"]
        agent_items = schema["properties"]["groups"]["items"]["properties"]["agents"]["items"]
        assert agent_items["properties"]["agent_type"]["enum"] == ["automotive_compliance"]


# ═══════════════════════════════════════════════════════════════════════════
# convert_floats_to_decimal (core/dynamodb.py)
#
# DynamoDB doesn't accept float — this recursively converts to Decimal.
# ═══════════════════════════════════════════════════════════════════════════


class TestConvertFloats:
    def test_float_becomes_decimal(self):
        assert convert_floats_to_decimal(3.14) == Decimal("3.14")

    def test_nested_dict(self):
        result = convert_floats_to_decimal({"score": 0.95, "count": 5})
        assert result["score"] == Decimal("0.95")
        assert result["count"] == 5

    def test_nested_list(self):
        result = convert_floats_to_decimal([1.1, 2.2])
        assert result == [Decimal("1.1"), Decimal("2.2")]

    def test_deeply_nested(self):
        result = convert_floats_to_decimal({"items": [{"value": 0.5}]})
        assert result["items"][0]["value"] == Decimal("0.5")

    def test_non_float_passthrough(self):
        assert convert_floats_to_decimal("hello") == "hello"
        assert convert_floats_to_decimal(42) == 42
        assert convert_floats_to_decimal(None) is None
