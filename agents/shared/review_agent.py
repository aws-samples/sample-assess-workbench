"""Generic review agent runtime.

Builds a Pydantic structured output model dynamically from the agent's
declarative finding_schema in the registry. One codebase for all review
agents — the only per-agent variation is the AGENT_TYPE environment
variable, which determines which registry entry (and therefore which
schema, prompt, and coach guidance) to use.

Registry config is loaded lazily on first invocation (not at module
import time) to stay within AgentCore's 30s init timeout. The config
is cached for the lifetime of the container after first load.

Phase 2 agentic tools:
- Agent has ``search_document``, ``get_prior_findings``, and
  ``lookup_standard`` tools wired unconditionally.
- ``LimitToolCounts`` plugin caps per-tool call counts (from registry).
- Per-request context passed via ``invocation_state``.
- ``agent_tool_calls`` progress event emitted after completion for
  flow graph visualization.

Deployed into each agent directory at deploy time by deploy_agent.sh.
"""

import os
import logging
from datetime import date
from string import Template

from botocore.config import Config as BotocoreConfig
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from shared.registry_loader import load_config_from_registry
from shared.schema_builder import build_review_model, derive_severity
from shared.metrics import extract_metrics
from shared.tools.memory_tools import get_prior_findings
from shared.tools.kb_tools import search_document, lookup_standard
from shared.hooks import LimitToolCounts

logger = logging.getLogger(__name__)
app = BedrockAgentCoreApp()

# --- Module-level: only read env vars (no network calls) ---

AGENT_TYPE = os.environ["AGENT_TYPE"]
PROJECTS_TABLE = os.environ["PROJECTS_TABLE"]

# Guardrail env vars — set by deploy_agent.sh from SSM when a guardrail
# is deployed. Empty/unset means no guardrail (feature flag off).
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")

# Environment variables for KB and memory resources — set by Terraform,
# same pattern as SHARED_MEMORY_ARN on the workflow Lambda side.
SHARED_MEMORY_ARN = os.environ.get("SHARED_MEMORY_ARN", "")
DOCUMENT_KB_ID = os.environ.get("DOCUMENT_KB_ID", "")
STANDARDS_KB_ID = os.environ.get("STANDARDS_KB_ID", "")

# Platform context boundary — prepended to all review agent prompts.
# Prevents agents from conflating platform infrastructure (AWS regions,
# endpoints, account IDs visible in their runtime context) with the
# customer's design document content.
PLATFORM_CONTEXT_BOUNDARY = """\
## Platform Context Boundary

You are a review service running on cloud infrastructure. Details about your \
own hosting environment — such as AWS regions, service endpoints, account \
identifiers, or runtime configuration — may be visible in your context. This \
platform context is not part of the document under review.

Only assess content that originates from the submitted design document. If you \
encounter infrastructure details that do not originate from the document content \
itself, disregard them — they are artifacts of the platform you run on, not \
decisions made by the entity whose design you are reviewing.

When making a finding about deployment-specific configuration, your evidence \
must come from the document content. If the document does not address a \
deployment-specific concern, treat it as an evidence gap — not as \
non-compliance inferred from platform context.

## AWS Platform Facts

These facts describe how AWS services work. Apply them when the design under \
review uses AWS services, so that data-residency and third-party-disclosure \
findings are accurate. They describe the platform, not decisions made by the \
entity.

- AWS services such as Amazon Bedrock are managed AWS services, not independent \
third-party companies. Invoking a model through Amazon Bedrock is not a \
disclosure of data to the model provider (for example Anthropic): the provider \
does not receive the customer's data, and data submitted for inference is not \
used to train the base models.
- Data residency is determined by the AWS Region and the inference-profile type \
the design invokes — not by the model provider's country of headquarters. A \
regional model ID processes in that single Region; a geographic inference \
profile (for example an APAC profile) keeps processing within that geography; \
only a global inference profile can route requests outside the geography.
- Data transmitted between AWS Regions for cross-Region inference stays on the \
AWS network, is encrypted in transit, and does not traverse the public internet.
- Infer residency from the Region and inference profile the document specifies. \
Do not treat use of a US-headquartered provider's model as offshore processing \
when the design pins a regional or in-geography inference path.
- These are platform facts, not a guarantee about any specific design. If the \
document does not state the Region or inference-profile type for a data flow, \
treat it as an evidence gap — do not assume data leaves the jurisdiction, and \
do not assume it stays."""

# Fallback tool limits if the registry entry hasn't been re-seeded
# with tool_limits yet. Prevents breakage during rolling deploys.
DEFAULT_REVIEW_TOOL_LIMITS: dict[str, int] = {
    "search_document": 5,
    "get_prior_findings": 4,
    "lookup_standard": 3,
}

# --- Lazy-loaded on first invocation, cached for container lifetime ---

_config_cache = {}


def _get_config():
    """Load and cache registry config on first call.

    Creates the BedrockModel here (not at module level) because model_id
    comes from the registry, not from environment variables. The model
    object is cached for the container lifetime — same connection pooling
    behavior as the previous module-level instantiation.
    """
    if _config_cache:
        return _config_cache

    registry_config = load_config_from_registry(AGENT_TYPE, PROJECTS_TABLE)

    model_id = registry_config.get("model_id")
    if not model_id:
        raise RuntimeError(
            f"Agent '{AGENT_TYPE}' has no model_id in registry. "
            f"Run 'task deploy:seed' to update the agent registry."
        )

    schema_config = registry_config.get("finding_schema")
    if not schema_config:
        raise RuntimeError(
            f"Agent '{AGENT_TYPE}' has no finding_schema in registry. "
            f"Cannot build structured output model without a schema definition."
        )

    agent_type = registry_config.get("agent_type", AGENT_TYPE)

    _config_cache["schema_config"] = schema_config
    _config_cache["prompt_template"] = registry_config.get("prompt_template", "")
    _config_cache["review_model"] = build_review_model(agent_type, schema_config)
    _config_cache["tool_limits"] = registry_config.get("tool_limits") or DEFAULT_REVIEW_TOOL_LIMITS
    # BedrockModel cached for container lifetime — same connection pooling
    # as the previous module-level instantiation, just sourced from registry.
    model_kwargs: dict = {
        "model_id": model_id,
        "boto_client_config": BotocoreConfig(read_timeout=600),
    }
    if GUARDRAIL_ID:
        model_kwargs.update(
            {
                "guardrail_id": GUARDRAIL_ID,
                "guardrail_version": GUARDRAIL_VERSION,
                "guardrail_trace": "enabled",
                # redact flags disabled: when a guardrail policy triggers with
                # action=BLOCKED, Strands replaces the *entire* message content
                # with a placeholder string. This destroys structured output
                # (tool_use blocks are wiped), causing result.structured_output
                # to be None and the agent to return 0 findings.
                # PII masking is handled inline by the guardrail's ANONYMIZE
                # action — these whole-message redaction flags are a separate,
                # more aggressive mechanism incompatible with structured output.
                "guardrail_redact_input": False,
                "guardrail_redact_output": False,
            }
        )
        logger.info("Guardrail enabled: %s (version %s)", GUARDRAIL_ID, GUARDRAIL_VERSION)
    _config_cache["bedrock_model"] = BedrockModel(**model_kwargs)

    return _config_cache


def _build_tool_calls_detail(result) -> list[dict]:
    """Extract tool call details from Strands AgentResult for the progress event.

    Args:
        result: Strands AgentResult with metrics.

    Returns:
        List of tool call summary dicts for the ``agent_tool_calls`` event.
    """
    tool_calls = []
    try:
        if result.metrics and result.metrics.tool_metrics:
            for name, tm in result.metrics.tool_metrics.items():
                tool_calls.append(
                    {
                        "tool": name,
                        "calls": tm.call_count,
                        "total_time_s": round(tm.total_time, 2) if hasattr(tm, "total_time") else 0,
                    }
                )
    except Exception:
        logger.warning("Failed to extract tool call details", exc_info=True)
    return tool_calls


@app.entrypoint
def invoke(payload):
    """Generic AgentCore entrypoint for review agents."""
    if "document_content" not in payload:
        return {"error": "Payload must contain 'document_content'"}

    config = _get_config()
    schema_config = config["schema_config"]
    prompt_template = config["prompt_template"]
    ReviewModel = config["review_model"]
    tool_limits = config["tool_limits"]

    # All three tools wired unconditionally. The tools themselves
    # validate required invocation_state and return clear errors
    # if a KB or memory resource isn't configured.
    tools = [search_document, get_prior_findings, lookup_standard]
    plugins = [LimitToolCounts(max_tool_counts=tool_limits)]

    # Build invocation_state with all resource coordinates.
    # memory_id comes from the payload (set by invoke_review_agent.py),
    # falling back to the env var for backward compatibility.
    memory_id_env = SHARED_MEMORY_ARN.split("/")[-1] if SHARED_MEMORY_ARN else ""
    memory_id = payload.get("memory_id", memory_id_env)
    invocation_state = {
        "project_id": payload.get("project_id", ""),
        "memory_id": memory_id,
        "document_kb_id": payload.get("document_kb_id", DOCUMENT_KB_ID),
        "standards_kb_id": payload.get("standards_kb_id", STANDARDS_KB_ID),
        "self_agent_type": AGENT_TYPE,
    }

    # Per-call Agent — Strands Agent accumulates conversation history in its
    # messages attribute across calls. Each review is an independent document,
    # so we need a fresh Agent per invocation to guarantee isolation.
    # The BedrockModel is reused (stateless), only the Agent is per-call.
    agent = Agent(
        model=config["bedrock_model"],
        tools=tools,
        plugins=plugins,
        structured_output_model=ReviewModel,
    )

    prompt = (
        PLATFORM_CONTEXT_BOUNDARY
        + "\n\n"
        + Template(prompt_template).safe_substitute(
            organizational_context=payload.get(
                "organizational_context", "No organizational context provided."
            ),
            document_content=payload["document_content"],
            current_date=date.today().isoformat(),
        )
    )

    result = agent(prompt, invocation_state=invocation_state)

    if result.structured_output:
        output = result.structured_output.model_dump()

        # Apply declarative severity derivation if configured
        if schema_config.get("severity_source") == "derived":
            derive_severity(output.get("findings", []), schema_config)

        output["metrics"] = extract_metrics(result)
        output["tool_calls"] = _build_tool_calls_detail(result)
        return output
    else:
        return {"error": "Failed to get structured output from agent"}


if __name__ == "__main__":
    app.run()
