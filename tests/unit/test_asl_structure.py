"""Structural contract tests for the review workflow ASL definition.

These tests validate invariants of the state machine structure that,
if broken, cause silent runtime failures. They load the raw JSON file
(with Terraform templatefile placeholders still present) and check
graph reachability, variable contracts, and placeholder wiring.

No AWS credentials or mocks needed — pure JSON analysis.
"""
import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ASL_PATH = Path(__file__).parent.parent.parent / "terraform" / "modules" / "workflow" / "statemachine" / "review_workflow.asl.json"
STATE_MACHINE_TF_PATH = Path(__file__).parent.parent.parent / "terraform" / "modules" / "workflow" / "state_machine.tf"


@pytest.fixture(scope="module")
def asl() -> dict:
    """Load the ASL definition as a dict."""
    return json.loads(ASL_PATH.read_text())


@pytest.fixture(scope="module")
def top_level_states(asl) -> dict:
    """Top-level States map (excludes states nested inside Map iterators)."""
    return asl["States"]


@pytest.fixture(scope="module")
def tf_source() -> str:
    """Raw text of state_machine.tf for placeholder cross-referencing."""
    return STATE_MACHINE_TF_PATH.read_text()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_all_states(states: dict, prefix: str = "") -> dict[str, dict]:
    """Recursively collect every state from the ASL, including Map iterators.

    Returns a flat dict of fully-qualified state name → state definition.
    Qualified names use '>' as separator (e.g. "ExecuteGroups>ExecuteAgentsInGroup").
    """
    result = {}
    for name, defn in states.items():
        qualified = f"{prefix}>{name}" if prefix else name
        result[qualified] = defn

        # Recurse into Map Iterator states
        if defn.get("Type") == "Map" and "Iterator" in defn:
            inner_states = defn["Iterator"].get("States", {})
            result.update(collect_all_states(inner_states, qualified))

    return result


def reachable_state_names(states: dict, start: str) -> set[str]:
    """BFS from start to find all reachable state names within a States map.

    Follows Next, Default, Catch[].Next, and Iterator StartAt.
    """
    visited: set[str] = set()
    queue = [start]

    while queue:
        current = queue.pop(0)
        if current in visited or current not in states:
            continue
        visited.add(current)
        defn = states[current]

        # Next
        if "Next" in defn:
            queue.append(defn["Next"])

        # Choice branches
        for choice in defn.get("Choices", []):
            if "Next" in choice:
                queue.append(choice["Next"])

        # Default (Choice states)
        if "Default" in defn:
            queue.append(defn["Default"])

        # Catch blocks
        for catch in defn.get("Catch", []):
            if "Next" in catch:
                queue.append(catch["Next"])

        # Map Iterator — recurse into inner scope separately
        # (inner states are a separate namespace, not siblings)

    return visited


# ---------------------------------------------------------------------------
# Test: InitWorkflow is StartAt and assigns all required context variables
# ---------------------------------------------------------------------------

REQUIRED_CONTEXT_VARIABLES = {
    "project_id",
    "review_id",
    "s3_bucket",
    "s3_key",
    "connection_id",
    "user_sub",
    "websocket_endpoint",
    "files",
}


class TestInitWorkflow:
    """InitWorkflow must be the entry point and assign all context variables."""

    def test_start_at_is_init_workflow(self, asl):
        assert asl["StartAt"] == "InitWorkflow"

    def test_init_workflow_is_pass_state(self, top_level_states):
        assert top_level_states["InitWorkflow"]["Type"] == "Pass"

    def test_assigns_all_required_context_variables(self, top_level_states):
        assign_block = top_level_states["InitWorkflow"].get("Assign", {})
        assigned_vars = {key.removesuffix(".$") for key in assign_block}
        missing = REQUIRED_CONTEXT_VARIABLES - assigned_vars
        assert not missing, f"InitWorkflow missing variable assignments: {missing}"


# ---------------------------------------------------------------------------
# Test: No orphaned states (every state reachable from StartAt)
# ---------------------------------------------------------------------------

class TestReachability:
    """Every state must be reachable from StartAt via Next/Default/Catch."""

    def test_top_level_no_orphans(self, asl):
        states = asl["States"]
        reachable = reachable_state_names(states, asl["StartAt"])
        all_names = set(states.keys())
        orphaned = all_names - reachable
        assert not orphaned, f"Orphaned top-level states: {orphaned}"

    def test_map_iterators_no_orphans(self, asl):
        """Check each Map iterator's states are internally reachable."""
        all_states = collect_all_states(asl["States"])
        for qualified_name, defn in all_states.items():
            if defn.get("Type") != "Map" or "Iterator" not in defn:
                continue
            iterator = defn["Iterator"]
            inner_states = iterator.get("States", {})
            start = iterator.get("StartAt")
            assert start, f"{qualified_name} Map has no StartAt"
            reachable = reachable_state_names(inner_states, start)
            orphaned = set(inner_states.keys()) - reachable
            assert not orphaned, (
                f"Orphaned states in {qualified_name} iterator: {orphaned}"
            )


# ---------------------------------------------------------------------------
# Test: templatefile placeholders match state_machine.tf variables
# ---------------------------------------------------------------------------

class TestTemplatePlaceholders:
    """Every ${...} placeholder in the ASL must be wired in state_machine.tf and vice versa."""

    def test_all_asl_placeholders_have_tf_variables(self, tf_source):
        asl_text = ASL_PATH.read_text()

        # Find ${...} placeholders in ASL (Terraform templatefile syntax)
        asl_placeholders = set(re.findall(r'\$\{(\w+)\}', asl_text))

        # Find variable names in the templatefile() call in state_machine.tf
        tf_block_match = re.search(
            r'templatefile\([^,]+,\s*\{(.*?)\}\s*\)',
            tf_source,
            re.DOTALL,
        )
        assert tf_block_match, "Could not find templatefile() block in state_machine.tf"
        tf_block = tf_block_match.group(1)
        tf_template_vars = set(re.findall(r'(\w+)\s*=', tf_block))

        missing_in_tf = asl_placeholders - tf_template_vars
        missing_in_asl = tf_template_vars - asl_placeholders

        assert not missing_in_tf, (
            f"ASL placeholders not wired in state_machine.tf templatefile(): {missing_in_tf}"
        )
        assert not missing_in_asl, (
            f"state_machine.tf templatefile() vars not used in ASL: {missing_in_asl}"
        )


# ---------------------------------------------------------------------------
# Test: Task states with Assign must have ResultPath: null
# ---------------------------------------------------------------------------

class TestAssignResultPath:
    """Task states using Assign must set ResultPath to null.

    Without ResultPath: null, the Lambda result overwrites state data,
    and the Assign references (which read from the result) may still work
    but the state data becomes the raw Lambda response — breaking any
    downstream state that reads from $.field paths in the state data.
    """

    def test_task_states_with_assign_have_null_result_path(self, asl):
        all_states = collect_all_states(asl["States"])
        violations = []
        for qualified_name, defn in all_states.items():
            if defn.get("Type") != "Task":
                continue
            if "Assign" not in defn:
                continue
            if defn.get("ResultPath") is not None:
                violations.append(qualified_name)

        assert not violations, (
            f"Task states with Assign but missing ResultPath: null — "
            f"{violations}"
        )


# ---------------------------------------------------------------------------
# Test: ASL ItemSelector fields must match the plan agent schema
# ---------------------------------------------------------------------------

class TestAgentPlanContract:
    """The ASL's ExecuteAgentsInGroup ItemSelector reads specific fields from
    each agent entry in the plan. The plan is produced by ``validate_plan``
    in ``core.plan_validation``. If the two drift (e.g. a field is removed
    from the plan schema but left in the ItemSelector), Step Functions
    fails at runtime with ``States.Runtime: JSONPath ... could not be
    found in the input`` and the review silently dies.

    This test catches that drift at unit-test time — no deploy needed.
    """

    @pytest.fixture(scope="class")
    def asl_item_selector_fields(self, asl) -> set[str]:
        """Extract the set of fields the ASL's ExecuteAgentsInGroup reads.

        Each entry looks like ``"foo.$": "$$.Map.Item.Value.foo"``. We
        strip the ``.$`` suffix to get the field name.
        """
        all_states = collect_all_states(asl["States"])
        # ExecuteAgentsInGroup is nested inside ExecuteGroups Map
        map_state = next(
            (defn for name, defn in all_states.items() if name.endswith(">ExecuteAgentsInGroup")),
            None,
        )
        assert map_state is not None, "ExecuteAgentsInGroup Map state not found"
        item_selector = map_state.get("ItemSelector")
        assert item_selector, "ExecuteAgentsInGroup has no ItemSelector"
        return {key.removesuffix(".$") for key in item_selector if key.endswith(".$")}

    @pytest.fixture(scope="class")
    def validated_plan_agent_fields(self) -> set[str]:
        """Extract the set of fields produced by ``validate_plan`` per agent.

        Runs validate_plan on a minimal plan and inspects an output agent
        entry. This is the authoritative source of what the ASL will
        actually receive at runtime.
        """
        from core.plan_validation import validate_plan

        raw_plan = {
            "groups": [
                {
                    "group_id": "g1",
                    "label": "Test",
                    "execution": "parallel",
                    "agents": [
                        {
                            "agent_type": "security",
                            "depth": "standard",
                            "focus_areas": [],
                            "prompt_addendum": "",
                            "judge": {},
                            "coach_guidance": "",
                        },
                    ],
                },
            ],
        }
        validated = validate_plan(raw_plan, available_agents={"security"})
        agent = validated["groups"][0]["agents"][0]
        return set(agent.keys())

    def test_asl_reads_only_fields_the_plan_produces(
        self, asl_item_selector_fields, validated_plan_agent_fields
    ):
        """Every field the ASL reads from an agent must exist in the plan.

        If this fails, Step Functions will fail at runtime with
        ``States.Runtime`` on every review. This was the `depends_on`
        regression in April 2026.
        """
        missing_in_plan = asl_item_selector_fields - validated_plan_agent_fields
        assert not missing_in_plan, (
            f"ASL ItemSelector reads fields not produced by validate_plan: "
            f"{missing_in_plan}. The plan schema and ASL ItemSelector "
            f"have drifted — Step Functions will fail with "
            f"States.Runtime on every review. "
            f"Either remove the field from the ASL or add it to validate_plan."
        )

    def test_plan_fields_are_consumed_by_asl(
        self, asl_item_selector_fields, validated_plan_agent_fields
    ):
        """Every field the plan produces should be read by the ASL.

        A field in the plan that the ASL doesn't read is dead data —
        wasted bytes in the state machine execution and a sign of
        incomplete cleanup. Not a runtime error, but a code smell worth
        catching.
        """
        dead_fields = validated_plan_agent_fields - asl_item_selector_fields
        assert not dead_fields, (
            f"validate_plan produces fields the ASL doesn't read: "
            f"{dead_fields}. These are dead data. Either remove them "
            f"from validate_plan or wire them into the ASL ItemSelector."
        )


# ---------------------------------------------------------------------------
# Test: ASL Lambda Payload fields match each Lambda's EXPECTED_EVENT
# ---------------------------------------------------------------------------

# Map ASL templatefile placeholder names to Python module paths.
# Each entry is (placeholder_suffix, module_import_path).
_LAMBDA_MODULE_MAP = {
    'load_document_fn': 'workflow.load_document',
    'index_document_fn': 'workflow.index_document',
    'plan_review_fn': 'workflow.plan_review',
    'store_plan_fn': 'workflow.store_plan',
    'resolve_agent_arns_fn': 'workflow.resolve_agent_arns',
    'invoke_review_agent_fn': 'workflow.invoke_review_agent',
    'invoke_judge_fn': 'workflow.invoke_judge',
    'notify_agent_status_fn': 'workflow.notify_agent_status',
    'aggregate_results_fn': 'workflow.aggregate_results',
    'merge_quality_fn': 'workflow.merge_quality',
    'store_results_fn': 'workflow.store_results',
    'update_status_failed_fn': 'workflow.update_status_failed',
    'post_completion_error_fn': 'workflow.post_completion_error',
}


def _extract_payload_fields(payload: dict) -> set[str]:
    """Extract field names from an ASL Payload block.

    Payload entries look like ``"field.$": "$variable"`` or ``"field": "literal"``.
    Strip the ``.$`` suffix to get the logical field name.
    """
    fields = set()
    for key in payload:
        fields.add(key.removesuffix('.$'))
    return fields


def _find_lambda_invocations(asl: dict) -> list[dict]:
    """Find all Task states that invoke Lambdas and extract their Payload fields.

    Returns a list of dicts with keys:
        - state_name: Qualified state name (e.g. "LoadDocument" or "ExecuteGroups>...>InvokeAgent")
        - placeholder: The templatefile placeholder (e.g. "load_document_fn")
        - payload_fields: Set of field names from the Payload block
    """
    all_states = collect_all_states(asl['States'])
    invocations = []

    for qualified_name, defn in all_states.items():
        if defn.get('Type') != 'Task':
            continue
        params = defn.get('Parameters', {})
        fn_name = params.get('FunctionName', '')

        # Match "${placeholder}" pattern
        match = re.match(r'^\$\{(\w+)\}$', fn_name)
        if not match:
            continue

        placeholder = match.group(1)
        payload = params.get('Payload', {})
        if not payload:
            continue

        invocations.append({
            'state_name': qualified_name,
            'placeholder': placeholder,
            'payload_fields': _extract_payload_fields(payload),
        })

    return invocations


class TestLambdaPayloadContract:
    """Every Task state that invokes a Lambda must send exactly the fields
    the Lambda declares in its EXPECTED_EVENT.

    This catches two classes of drift:
    1. ASL sends a field the Lambda doesn't declare → dead data (warning-level).
    2. ASL omits a field the Lambda declares as required → runtime KeyError.

    Each Lambda declares EXPECTED_EVENT at module level:
        EXPECTED_EVENT = {
            'required': ['project_id', 'review_id'],
            'optional': ['connection_id', 'websocket_endpoint'],
        }
    """

    @pytest.fixture(scope='class')
    def lambda_invocations(self, asl) -> list[dict]:
        """All Lambda invocations found in the ASL."""
        return _find_lambda_invocations(asl)

    @pytest.fixture(scope='class')
    def lambda_contracts(self) -> dict[str, dict]:
        """Load EXPECTED_EVENT from each workflow Lambda module.

        Uses AST parsing instead of importing to avoid triggering
        module-level side effects (boto3 clients, env var checks).

        Returns {placeholder: {'required': set, 'optional': set, 'module': str}}.
        """
        import ast

        api_dir = Path(__file__).parent.parent.parent / 'api'
        contracts = {}
        for placeholder, module_path in _LAMBDA_MODULE_MAP.items():
            file_path = api_dir / module_path.replace('.', '/') 
            file_path = file_path.with_suffix('.py')
            assert file_path.exists(), (
                f"Lambda module not found: {file_path} "
                f"(placeholder: {placeholder})"
            )

            tree = ast.parse(file_path.read_text())
            expected = None
            for node in ast.iter_child_nodes(tree):
                if (isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == 'EXPECTED_EVENT'):
                    expected = ast.literal_eval(node.value)
                    break

            assert expected is not None, (
                f"{module_path} is missing EXPECTED_EVENT declaration. "
                f"Add it to declare the Lambda's event contract."
            )
            contracts[placeholder] = {
                'required': set(expected['required']),
                'optional': set(expected.get('optional', [])),
                'module': module_path,
            }
        return contracts

    def test_every_lambda_has_expected_event(self, lambda_contracts):
        """Verify all mapped Lambdas have EXPECTED_EVENT declarations."""
        # This is implicitly tested by the fixture assertion, but having
        # an explicit test makes failures visible in the test explorer.
        for placeholder, contract in lambda_contracts.items():
            assert contract['required'] is not None or contract['optional'] is not None, (
                f"{contract['module']} EXPECTED_EVENT is empty"
            )

    def test_asl_sends_all_required_fields(self, lambda_invocations, lambda_contracts):
        """Every required field in EXPECTED_EVENT must appear in the ASL Payload.

        If this fails, the Lambda will crash with KeyError at runtime.
        """
        missing = []
        for invocation in lambda_invocations:
            placeholder = invocation['placeholder']
            if placeholder not in lambda_contracts:
                continue
            contract = lambda_contracts[placeholder]
            required = contract['required']
            payload_fields = invocation['payload_fields']
            absent = required - payload_fields
            if absent:
                missing.append(
                    f"{invocation['state_name']} ({contract['module']}): "
                    f"missing required fields {sorted(absent)}"
                )

        assert not missing, (
            "ASL Payload is missing required fields declared by Lambdas:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_asl_sends_only_declared_fields(self, lambda_invocations, lambda_contracts):
        """Every field in the ASL Payload should be declared by the Lambda.

        Undeclared fields are dead data — the Lambda ignores them. Not a
        runtime error, but a sign of incomplete cleanup or a missing
        EXPECTED_EVENT entry.
        """
        undeclared = []
        for invocation in lambda_invocations:
            placeholder = invocation['placeholder']
            if placeholder not in lambda_contracts:
                continue
            contract = lambda_contracts[placeholder]
            all_declared = contract['required'] | contract['optional']
            payload_fields = invocation['payload_fields']
            extra = payload_fields - all_declared
            if extra:
                undeclared.append(
                    f"{invocation['state_name']} ({contract['module']}): "
                    f"undeclared fields {sorted(extra)}"
                )

        assert not undeclared, (
            "ASL Payload sends fields not declared in EXPECTED_EVENT:\n"
            + "\n".join(f"  - {u}" for u in undeclared)
            + "\nEither add them to EXPECTED_EVENT or remove them from the ASL Payload."
        )

    def test_all_asl_lambdas_are_mapped(self, lambda_invocations):
        """Every Lambda placeholder in the ASL should have a module mapping.

        If this fails, a new Lambda was added to the ASL but not to
        _LAMBDA_MODULE_MAP — its contract won't be validated.
        """
        unmapped = []
        for invocation in lambda_invocations:
            placeholder = invocation['placeholder']
            if placeholder not in _LAMBDA_MODULE_MAP:
                unmapped.append(
                    f"{invocation['state_name']}: placeholder '{placeholder}' "
                    f"has no entry in _LAMBDA_MODULE_MAP"
                )

        assert not unmapped, (
            "ASL Lambda invocations without module mappings:\n"
            + "\n".join(f"  - {u}" for u in unmapped)
            + "\nAdd entries to _LAMBDA_MODULE_MAP in test_asl_structure.py."
        )
