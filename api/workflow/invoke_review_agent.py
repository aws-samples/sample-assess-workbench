"""
Invoke Review Agent Lambda — Generic agent invoker driven by the review plan.
Called by Step Functions Map state for each agent in each group.

Receives agent config (type, depth, focus_areas, prompt_addendum) and the
resolved agent_arn from the plan. Constructs the appropriate payload for the
AgentCore agent.
"""
import json
import logging
import os
import time
import boto3
from botocore.config import Config as BotocoreConfig

from core.progress import send_progress, set_user_sub, set_review_context
from core.coach_logic import build_org_context
from core.s3 import read_json
from core.agentcore import parse_agentcore_response
from core.memory import build_finding_records, store_records_in_memory

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    'required': ['agent_type', 's3_bucket', 'document_s3_key', 'project_id', 'review_id'],
    'optional': ['agent_arns', 'depth', 'focus_areas', 'prompt_addendum',
                 'connection_id', 'user_sub', 'websocket_endpoint',
                 'prior_critique', 'prior_findings', 'prior_strengths',
                 'prior_gaps', 'iteration', 'max_iterations'],
}

agentcore_client = boto3.client(
    'bedrock-agentcore',
    config=BotocoreConfig(read_timeout=600),
)

SHARED_MEMORY_ARN = os.environ.get('SHARED_MEMORY_ARN', '')
DOCUMENT_KB_ID = os.environ.get('DOCUMENT_KB_ID', '')
STANDARDS_KB_ID = os.environ.get('STANDARDS_KB_ID', '')


def lambda_handler(event: dict, context) -> dict:
    agent_type = event['agent_type']
    agent_arns = event.get('agent_arns', {})
    agent_arn = agent_arns.get(agent_type)
    if not agent_arn:
        raise ValueError(f"No agent_arn in agent_arns map for agent type: {agent_type}")

    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '')
    set_user_sub(event.get('user_sub', ''))
    set_review_context(event['project_id'], event['review_id'])
    project_id = event['project_id']
    review_id = event['review_id']

    send_progress(connection_id, websocket_endpoint, 'agent_started', {
        'agent': agent_type,
        'depth': event.get('depth', 'standard'),
        'focus_areas': event.get('focus_areas', []),
        'iteration': event.get('iteration', 0),
        'max_iterations': event.get('max_iterations', 0),
    })

    try:
        # Read document content from S3 (not carried in state machine payload)
        s3_bucket = event['s3_bucket']
        document_s3_key = event['document_s3_key']
        doc_data = read_json(s3_bucket, document_s3_key)
        document_content = doc_data['document_content']

        org_context = build_org_context(
            base_context=doc_data.get('organizational_context', ''),
            depth=event.get('depth', 'standard'),
            focus_areas=event.get('focus_areas', []),
            prompt_addendum=event.get('prompt_addendum', ''),
            prior_critique=event.get('prior_critique', ''),
            prior_findings=event.get('prior_findings'),
            prior_strengths=event.get('prior_strengths'),
            prior_gaps=event.get('prior_gaps'),
            iteration=event.get('iteration', 0),
        )

        # Memory ID extracted from ARN — same pattern as review_agent.py.
        memory_id = SHARED_MEMORY_ARN.split('/')[-1] if SHARED_MEMORY_ARN else ''

        payload = {
            'document_content': document_content,
            'organizational_context': org_context,
            'project_id': project_id,
            'memory_id': memory_id,
            'document_kb_id': DOCUMENT_KB_ID,
            'standards_kb_id': STANDARDS_KB_ID,
        }

        # Invoke the agent
        invoke_start = time.time()
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            runtimeSessionId=f"{project_id}_{review_id}_{context.aws_request_id}",
            payload=json.dumps(payload).encode('utf-8'),
        )

        result_text = parse_agentcore_response(response)
        findings = json.loads(result_text)

        # Detect agent-level errors (e.g. guardrail blocked structured output).
        # Without this check, {"error": "..."} silently becomes 0 findings.
        if 'error' in findings:
            error_msg = findings['error']
            logger.error("Agent %s returned error: %s", agent_type, error_msg)
            send_progress(connection_id, websocket_endpoint, 'agent_error', {
                'agent': agent_type,
                'error': error_msg,
            })
            raise RuntimeError(f"Agent {agent_type} failed: {error_msg}")

        finding_count = len(findings.get('findings', []))
        agent_metrics = findings.get('metrics', {})
        agent_metrics['lambda_duration_s'] = round(time.time() - invoke_start, 2)
        logger.info(f"Agent {agent_type} returned {finding_count} findings, metrics keys: {list(agent_metrics.keys())}")

        send_progress(connection_id, websocket_endpoint, 'agent_completed', {
            'agent': agent_type,
            'finding_count': finding_count,
            'metrics': agent_metrics,
            'iteration': event.get('iteration', 0),
        })

        # Write this agent's findings to memory immediately so downstream
        # agents in later groups can retrieve them via get_prior_findings.
        # Uses the same requestIdentifier convention as aggregate_results,
        # so the aggregation batch write is a no-op for these records.
        memory_record_count = 0
        if SHARED_MEMORY_ARN and finding_count > 0:
            try:
                memory_id = SHARED_MEMORY_ARN.split('/')[-1]
                records = build_finding_records(
                    findings=findings.get('findings', []),
                    agent_type=agent_type,
                    project_id=project_id,
                )
                memory_record_count = store_records_in_memory(
                    agentcore_client, memory_id, records,
                )
                namespace = f"/findings/{project_id}/{agent_type}"
                send_progress(connection_id, websocket_endpoint, 'agent_memory_write', {
                    'agent': agent_type,
                    'records': memory_record_count,
                    'namespace': namespace,
                })
            except Exception as e:
                # Memory write failure is non-fatal — the agent's findings
                # are still returned to the state machine and will be written
                # by aggregate_results. Log at warning, not error.
                logger.warning(
                    "Failed to write %s findings to memory: %s",
                    agent_type, e,
                )

        # Emit agent_tool_calls progress event for flow graph visualization.
        # tool_calls is populated by the review agent runtime from Strands
        # AgentResult.metrics.tool_metrics.
        tool_calls = findings.get('tool_calls', [])
        if tool_calls:
            send_progress(connection_id, websocket_endpoint, 'agent_tool_calls', {
                'agent': agent_type,
                'tool_calls': tool_calls,
            })

        return {
            'agent_type': agent_type,
            'findings': findings.get('findings', []),
            'summary': findings.get('summary', ''),
            'metrics': agent_metrics,
        }

    except Exception as e:
        send_progress(connection_id, websocket_endpoint, 'agent_error', {
            'agent': agent_type,
            'error': str(e),
        })
        raise
