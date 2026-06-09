"""
Plan Review Lambda — Analyzes a document and produces a review plan.
Invoked by Step Functions after LoadDocument.

Uses Bedrock Converse API directly (not AgentCore) for a single
structured-output call. Fast (~3-5s) and cheap.
"""
import logging
import os
import time
import boto3

from core.plan_validation import validate_plan, build_plan_tool
from core.progress import send_progress, set_user_sub, set_review_context
from core.registry import load_agent_registry
from core.coach_logic import enrich_plan_with_guidance
from core.s3 import read_json

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    'required': ['s3_bucket', 'document_s3_key'],
    'optional': ['project_id', 'review_id', 'connection_id', 'user_sub', 'websocket_endpoint'],
}

bedrock = boto3.client('bedrock-runtime', config=boto3.session.Config(
    read_timeout=120,
    connect_timeout=10,
    retries={'max_attempts': 0},
))

PLANNER_PROMPT = """You are a review planning system. Analyze the following document and produce a review plan.

Available review agents:
{agent_descriptions}

Your job is to decide:
1. Which agents should review this document
2. In what order (which can run in parallel, which need to be sequential)
3. What each agent should focus on given this specific document

Guidelines:
- Before selecting agents, consider the document's jurisdiction, industry, and regulatory context. Match these against each agent's described scope. Do not select domain-specific agents (e.g., automotive compliance, EU regulatory) unless the document and organisational context clearly fall within that agent's stated scope. Generic agents (architecture, security, risk) are broadly applicable; compliance agents are not.
- For most documents, the generic agents (architecture, security, risk) are relevant. Only skip a generic agent if the document genuinely has nothing for it to review.
- Use parallel execution when agents are independent. Use sequential when one agent's findings should inform another.
- depth: "quick" (~30s, surface-level), "standard" (~60s, balanced), "thorough" (~90s, deep analysis)
- For high-complexity documents, prefer "thorough". For simple specs, "quick" or "standard" is fine.
- The prompt_addendum should be specific to THIS document. Reference specific technologies, patterns, or concerns you see in the document. Don't be generic.
- focus_areas should be specific to what you see in the document, not a generic list.

Organizational context (if provided):
{organizational_context}

Document (first 4000 characters for planning):
{document_preview}

Analyze the document and call the create_review_plan tool with your plan."""


def lambda_handler(event: dict, context) -> dict:
    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '')
    set_user_sub(event.get('user_sub', ''))
    set_review_context(event.get('project_id', ''), event.get('review_id', ''))

    # Read document content from S3 (no longer carried in state machine payload)
    s3_bucket = event['s3_bucket']
    document_s3_key = event['document_s3_key']
    doc_data = read_json(s3_bucket, document_s3_key)
    document_content = doc_data['document_content']
    organizational_context = doc_data.get('organizational_context', '')

    # Load agents from registry (cached per cold start)
    available_agents = load_agent_registry()

    send_progress(connection_id, websocket_endpoint, 'registry_loaded', {
        'agent_count': len(available_agents),
        'agents': list(available_agents.keys()),
    })

    # Use first 4000 chars for planning (enough to understand the doc, avoids token bloat)
    document_preview = document_content[:4000]

    agent_descriptions = '\n'.join(
        f"- {name}: {info['description']}"
        for name, info in available_agents.items()
    )

    prompt = PLANNER_PROMPT.format(
        agent_descriptions=agent_descriptions,
        organizational_context=organizational_context or 'None provided.',
        document_preview=document_preview,
    )

    # Build tool schema dynamically from available agent types
    agent_types = list(available_agents.keys())
    plan_tool = build_plan_tool(agent_types)

    send_progress(connection_id, websocket_endpoint, 'planning_started', {
        'agent_count': len(available_agents),
        'model_id': os.environ.get('PLANNER_MODEL_ID', 'us.anthropic.claude-sonnet-4-6'),
    })
    plan_start = time.time()

    # Use Bedrock Converse with toolUse to force structured JSON output.
    # The model is required to call the tool, which guarantees valid JSON
    # matching our schema — no code fence stripping or fragile parsing.
    model_id = os.environ.get('PLANNER_MODEL_ID', 'us.anthropic.claude-sonnet-4-6')
    logger.info(f'Calling bedrock.converse model={model_id} prompt_len={len(prompt)}')
    response = bedrock.converse(
        modelId=model_id,
        messages=[{'role': 'user', 'content': [{'text': prompt}]}],
        inferenceConfig={'maxTokens': 4096, 'temperature': 0.1},
        toolConfig={
            'tools': [plan_tool],
            'toolChoice': {'tool': {'name': 'create_review_plan'}},
        },
    )
    logger.info(f'Converse returned in {time.time() - plan_start:.1f}s')

    # Extract the structured tool use result
    plan = None
    for block in response['output']['message']['content']:
        if 'toolUse' in block:
            plan = block['toolUse']['input']
            break

    if not plan:
        raise RuntimeError(
            "Planner did not return tool use — unexpected Bedrock response format"
        )

    available_agent_set = set(available_agents.keys())
    plan = validate_plan(plan, available_agent_set)
    plan['plan_id'] = f"plan_{context.aws_request_id[:8]}"

    # Enrich plan agents with coach_guidance from registry and validate coach config
    plan = enrich_plan_with_guidance(plan, available_agents)

    send_progress(connection_id, websocket_endpoint, 'planning_complete', {
        'document_type': plan.get('document_type', 'unknown'),
        'complexity': plan.get('complexity', 'medium'),
        'agent_count': sum(len(g['agents']) for g in plan['groups']),
        'group_count': len(plan['groups']),
        'rationale': plan.get('rationale', ''),
        'planning_duration_ms': int((time.time() - plan_start) * 1000),
    })

    # Return plan and planning duration — context fields are already in
    # workflow variables from InitWorkflow. No need to echo the event.
    planning_duration_ms = int((time.time() - plan_start) * 1000)
    return {
        'plan': plan,
        'planning_duration_ms': planning_duration_ms,
    }



