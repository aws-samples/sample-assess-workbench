"""Generic chat agent runtime.

Streams conversational responses using the agent's prompt template from
the registry. One codebase for all chat agents — the only per-agent
variation is the AGENT_TYPE environment variable.

Registry config is loaded lazily on first invocation (not at module
import time) to stay within AgentCore's 30s init timeout. The config
is cached for the lifetime of the container after first load.

Key behavioral change from the per-agent chat agents:
- Agent is created per-call, not at module level. The old pattern leaked
  conversation history across requests on warm containers.
- model_id comes from the DynamoDB agent registry (no env var fallback).

Phase 2 agentic tools:
- Agent has ``search_findings`` tool when memory is configured.
- Agent has ``search_document`` tool when document KB is configured.
- Agent has ``lookup_standard`` tool when standards KB is configured.
- ``LimitToolCounts`` plugin caps per-tool call counts (from registry).
- Per-request context passed via ``invocation_state``.
- ``_usage`` metrics yielded as typed event after stream for frontend display.

Deployed into each agent directory at deploy time by deploy_agent.sh.
"""

import os
import logging
from datetime import date
from string import Template

import boto3
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from shared.registry_loader import load_config_from_registry
from shared.tools.memory_tools import search_findings
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
GUARDRAIL_EVENTS_TABLE = os.environ.get("GUARDRAIL_EVENTS_TABLE", "")

# Fallback tool limits if the registry entry hasn't been re-seeded
# with tool_limits yet. Prevents breakage during rolling deploys.
DEFAULT_CHAT_TOOL_LIMITS: dict[str, int] = {
    "search_findings": 4,
    "search_document": 3,
    "lookup_standard": 2,
}

# ── Prompt section templates ─────────────────────────────────────────
#
# Built dynamically based on which tools are wired for this request.
# Each tool gets a "when to use / when not to use" block only if it's
# available. The full section replaces $findings_section in the prompt.

_SECTION_HEADER = """\
## Available Tools

You have access to the following tools to help answer questions.

- Your agent type is: $self_agent_type"""

_SEARCH_FINDINGS_BLOCK = """
### search_findings
Look up review findings from your domain stored in memory.

**When to use:**
- When the user asks about specific findings, recommendations, or issues from a review
- When the user asks about a specific domain (e.g. "what did the security review find?")
- When you need to reference specific finding details (IDs, severity, descriptions)

**When NOT to use:**
- For greetings or general conversation
- For general knowledge questions about your domain (use your expertise)
- When the answer is already in the conversation history

**Tips:** Use specific, targeted queries rather than broad ones."""

_SEARCH_DOCUMENT_BLOCK = """
### search_document
Search the original document under review for specific sections.

**When to use:**
- When the user asks "what does the document say about X?"
- When you need to reference the source material directly
- When findings reference a document section and the user wants details

**When NOT to use:**
- When the user is asking about findings or recommendations (use search_findings)
- When you can answer from your expertise or conversation history

**Tips:** Include a section_hint if you know the heading name."""

_LOOKUP_STANDARD_BLOCK = """
### lookup_standard
Look up compliance standards, frameworks, or regulations.

**When to use:**
- When the user asks about a specific standard (e.g. "what does OWASP say about X?")
- When you need to cite accurate, current text from a standard
- When verifying whether a finding aligns with a specific regulation

**When NOT to use:**
- For general knowledge questions you can answer from expertise
- When the standard isn't relevant to the question

**Tips:** Provide the standard identifier and a section or query."""

_NO_TOOLS_SECTION = """\
Note: Review findings are not available for this project. Answer questions \
based on your expertise and the conversation history. If the user asks about \
specific review findings, let them know that no review data is available."""

# Participating agents section — tells the chat agent which review agents
# contributed findings so it can accurately direct users. Injected only
# when tools are available AND at least one agent participated.
_PARTICIPATING_AGENTS_SECTION = """\

### Participating Agents

The following agents contributed findings to this project's review: $agent_list.
You can search any of these agents' findings using the search_findings tool \
by targeting the appropriate agent type."""

# --- Lazy-loaded on first invocation, cached for container lifetime ---

_config_cache = {}


def _get_config():
    """Load and cache prompt template, model_id, and tool_limits on first call.

    All come from the DynamoDB agent registry. model_id is required —
    if missing, the registry entry is incomplete (run 'task deploy:seed').
    """
    if not _config_cache:
        registry_config = load_config_from_registry(AGENT_TYPE, PROJECTS_TABLE)

        model_id = registry_config.get("model_id")
        if not model_id:
            raise RuntimeError(
                f"Agent '{AGENT_TYPE}' has no model_id in registry. "
                f"Run 'task deploy:seed' to update the agent registry."
            )

        _config_cache["prompt_template"] = registry_config.get("prompt_template", "")
        _config_cache["model_id"] = model_id
        _config_cache["tool_limits"] = (
            registry_config.get("tool_limits") or DEFAULT_CHAT_TOOL_LIMITS
        )

        # BedrockModel cached for container lifetime. Chat agents previously
        # passed a string model_id to Agent() — constructing a BedrockModel
        # enables guardrail attachment and connection pooling across requests.
        model_kwargs: dict = {"model_id": model_id}
        if GUARDRAIL_ID:
            model_kwargs.update(
                {
                    "guardrail_id": GUARDRAIL_ID,
                    "guardrail_version": GUARDRAIL_VERSION,
                    "guardrail_trace": "enabled",
                    # redact flags disabled — same rationale as review_agent.py.
                    # Additionally, redact_input=True corrupts multi-turn context
                    # by replacing the user's message with a placeholder string.
                    "guardrail_redact_input": False,
                    "guardrail_redact_output": False,
                    "guardrail_latest_message": True,
                    "guardrail_stream_processing_mode": "sync",
                }
            )
            logger.info("Guardrail enabled: %s (version %s)", GUARDRAIL_ID, GUARDRAIL_VERSION)
        _config_cache["bedrock_model"] = BedrockModel(**model_kwargs)
    return _config_cache


def _build_tools_section(
    *,
    has_findings: bool,
    has_document_search: bool,
    has_standards_lookup: bool,
    self_agent_type: str,
    participating_agents: str,
) -> str:
    """Build the dynamic tools prompt section based on available tools.

    Args:
        has_findings: Whether search_findings is available.
        has_document_search: Whether search_document is available.
        has_standards_lookup: Whether lookup_standard is available.
        self_agent_type: The agent's own type identifier.
        participating_agents: Comma-separated list of participating agents.

    Returns:
        Prompt section string to substitute into $findings_section.
    """
    if not any([has_findings, has_document_search, has_standards_lookup]):
        return _NO_TOOLS_SECTION

    parts = [
        Template(_SECTION_HEADER).safe_substitute(
            self_agent_type=self_agent_type,
        )
    ]

    if has_findings:
        parts.append(_SEARCH_FINDINGS_BLOCK)
    if has_document_search:
        parts.append(_SEARCH_DOCUMENT_BLOCK)
    if has_standards_lookup:
        parts.append(_LOOKUP_STANDARD_BLOCK)

    # Participating agents section — only when findings tools are
    # available and at least one agent participated.
    if has_findings and participating_agents:
        agent_list = ", ".join(participating_agents.split(","))
        parts.append(
            Template(_PARTICIPATING_AGENTS_SECTION).safe_substitute(
                agent_list=agent_list,
            )
        )

    return "\n".join(parts)


def _persist_guardrail_event(
    *,
    project_id: str,
    agent_type: str,
    user_sub: str = "",
    user_email: str = "",
) -> None:
    """Write a guardrail intervention event to the audit table.

    Creates a per-call boto3 client because AgentCore containers handle
    concurrent requests and boto3 clients are not thread-safe.

    Args:
        project_id: Project the chat was about.
        agent_type: Chat agent type identifier.
        user_sub: Cognito user sub from the chat payload.
        user_email: Cognito user email from the chat payload.
    """
    import uuid
    from datetime import datetime, timezone as tz

    now = datetime.now(tz=tz.utc)
    timestamp = now.isoformat()
    short_id = uuid.uuid4().hex[:8]

    table = boto3.resource("dynamodb").Table(GUARDRAIL_EVENTS_TABLE)
    item = {
        "PK": f"YEAR#{now.year}",
        "SK": f"{timestamp}#{short_id}",
        "timestamp": timestamp,
        "project_id": project_id,
        "agent_type": agent_type,
        "agent_role": "chat",
        "action_taken": "intervened",
    }
    if user_sub:
        item["user_sub"] = user_sub
    if user_email:
        item["user_email"] = user_email

    table.put_item(Item=item)


@app.entrypoint
async def invoke(payload):
    """Generic AgentCore entrypoint for chat agents."""
    if "question" not in payload:
        yield '{"error": "Payload must contain question"}'
        return

    config = _get_config()
    prompt_template = config["prompt_template"]
    tool_limits = config["tool_limits"]

    # Extract resource coordinates from payload.
    memory_id = payload.get("shared_memory_id", "")
    project_id = payload.get("project_id", "")
    self_agent_type = payload.get("agent_type", AGENT_TYPE)
    document_kb_id = payload.get("document_kb_id", "")
    standards_kb_id = payload.get("standards_kb_id", "")

    # Conditionally wire tools based on resource availability.
    tools = []
    invocation_state = {}
    has_findings = bool(memory_id)
    has_document_search = bool(document_kb_id)
    has_standards_lookup = bool(standards_kb_id)

    if has_findings:
        tools.append(search_findings)
        invocation_state["project_id"] = project_id
        invocation_state["memory_id"] = memory_id
        invocation_state["self_agent_type"] = self_agent_type

    if has_document_search:
        tools.append(search_document)
        invocation_state["project_id"] = project_id
        invocation_state["document_kb_id"] = document_kb_id

    if has_standards_lookup:
        tools.append(lookup_standard)
        invocation_state["standards_kb_id"] = standards_kb_id

    # Only add plugins and invocation_state when tools are present.
    plugins = []
    if tools:
        plugins.append(LimitToolCounts(max_tool_counts=tool_limits))
    else:
        invocation_state = None

    # Per-call Agent — fixes the conversation history leak bug in the
    # old per-agent chat agents. Each chat request is independent (chat
    # history is passed in the payload, not held in the Agent).
    agent = Agent(
        model=config["bedrock_model"],
        tools=tools,
        plugins=plugins,
        callback_handler=None,
    )

    question = payload["question"]
    findings_section = _build_tools_section(
        has_findings=has_findings,
        has_document_search=has_document_search,
        has_standards_lookup=has_standards_lookup,
        self_agent_type=self_agent_type,
        participating_agents=payload.get("participating_agents", ""),
    )

    # Build participating agents section — empty string when handled
    # inside _build_tools_section (it's folded into the tools section now).
    participating_agents_section = ""

    chat_history = payload.get("chat_history", "")
    chat_history_section = chat_history if chat_history else "No previous conversation."

    prompt = Template(prompt_template).safe_substitute(
        organizational_context=payload.get(
            "organizational_context", "No organizational context provided."
        ),
        project_name=payload.get("project_name", "Unknown Project"),
        project_description=payload.get("project_description", ""),
        project_id=payload.get("project_id", "unknown"),
        findings_section=findings_section,
        participating_agents_section=participating_agents_section,
        chat_history=chat_history_section,
        question=question,
        current_date=date.today().isoformat(),
    )

    # Use the explicit invocation_state parameter — **kwargs is
    # deprecated in Strands stream_async.
    agent_stream = agent.stream_async(prompt, invocation_state=invocation_state)
    agent_result = None
    async for event in agent_stream:
        if "data" in event:
            yield event["data"]
        if "result" in event:
            agent_result = event["result"]

    # Log guardrail interventions for observability. The guardrail trace
    # (enabled via guardrail_trace="enabled") contains which policies
    # triggered and what action was taken. Logged at WARNING so it's
    # visible in CloudWatch without noise at INFO level.
    if agent_result and getattr(agent_result, "stop_reason", None) == "guardrail_intervened":
        project_id_log = payload.get("project_id", "unknown")
        logger.warning(
            "Guardrail intervened for chat agent %s (project %s): stop_reason=%s",
            AGENT_TYPE,
            project_id_log,
            agent_result.stop_reason,
        )

        # Persist to guardrail events table for admin dashboard visibility.
        # Non-fatal — if the write fails, the CloudWatch log above still
        # provides observability. Uses per-call boto3 client because
        # AgentCore containers handle concurrent requests.
        if GUARDRAIL_EVENTS_TABLE:
            try:
                _persist_guardrail_event(
                    project_id=project_id_log,
                    agent_type=AGENT_TYPE,
                    user_sub=payload.get("user_sub", ""),
                    user_email=payload.get("user_email", ""),
                )
            except Exception:
                logger.warning(
                    "Failed to persist guardrail event for %s (project %s)",
                    AGENT_TYPE,
                    project_id_log,
                    exc_info=True,
                )

    # Yield usage metrics as a typed event after the text stream completes.
    # stream_async yields {"result": AgentResult} as its final event.
    # AgentResult.metrics is an EventLoopMetrics with accumulated_usage.
    #
    # We yield a dict (not json.dumps) — AgentCore's _convert_to_sse calls
    # json.dumps on each yield. Yielding a string would double-encode it.
    # The WebSocket handler detects dicts with a "type" field and routes
    # them as separate WebSocket events instead of text chunks.
    if agent_result and hasattr(agent_result, "metrics") and agent_result.metrics:
        try:
            usage = agent_result.metrics.accumulated_usage or {}
            yield {
                "type": "usage",
                "model_id": config["model_id"],
                "input_tokens": usage.get("inputTokens", 0),
                "output_tokens": usage.get("outputTokens", 0),
                "total_tokens": usage.get("totalTokens", 0),
                "tool_calls": sum(
                    tm.call_count for tm in (agent_result.metrics.tool_metrics or {}).values()
                ),
                "cycles": len(agent_result.metrics.cycle_durations)
                if agent_result.metrics.cycle_durations
                else 0,
            }
        except Exception:
            logger.warning("Failed to yield usage metrics", exc_info=True)


if __name__ == "__main__":
    app.run()
