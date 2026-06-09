"""
Benchmark Runner Lambda — Executes all configurations for a benchmark in parallel.

For each configuration:
1. Loads the document from S3
2. Invokes the review agent with the config's model_id and depth
3. Runs the judge evaluator on the results
4. Stores findings + scores + metrics as a benchmark run record

Invoked asynchronously by the API Lambda via InvocationType='Event'.
"""
import json
import logging
import os
import time
from botocore.config import Config as BotocoreConfig
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import boto3

from core.registry import load_agent_registry
from core.dynamodb import convert_floats_to_decimal
from core.s3 import read_text
from core.coach_logic import DEPTH_INSTRUCTIONS, normalize_evaluation, JUDGE_TOOL

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))


# Clients

bedrock = boto3.client('bedrock-runtime', config=BotocoreConfig(read_timeout=600))
dynamodb = boto3.resource('dynamodb')

TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
S3_BUCKET = os.environ['S3_BUCKET_NAME']
JUDGE_MODEL_ID = os.environ.get('JUDGE_MODEL_ID', 'us.anthropic.claude-sonnet-4-6')
PROJECT_NAME = os.environ.get('PROJECT_NAME', 'risk-assessor')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

JUDGE_PROMPT = """You are a quality judge for {agent_type} reviews. Evaluate the following findings against the document and focus areas.

Score each criterion from 0.0 to 1.0:
- completeness: Are all relevant aspects covered? Are there obvious gaps?
- specificity: Do findings reference specific parts of the document?
- actionability: Can a team act on each finding without further clarification?

Quality threshold: 0.8

Document preview:
{document_preview}

Findings to evaluate:
{findings_json}"""


def _load_document(s3_bucket: str, s3_key: str) -> str:
    """Load document text from S3.

    Args:
        s3_bucket: S3 bucket name.
        s3_key: S3 object key.

    Returns:
        The document text.

    Raises:
        RuntimeError: If the S3 read fails.
    """
    return read_text(s3_bucket, s3_key)


def _invoke_agent_direct(
    model_id: str, agent_type: str, document_content: str,
    depth: str, registry_entry: dict,
) -> dict:
    """Invoke a review agent via Bedrock Converse directly.

    Bypasses AgentCore to allow per-config model selection. Uses the prompt
    template and tool schema from the agent registry.

    Args:
        model_id: Bedrock model ID from the benchmark config
        agent_type: Agent type (architecture, security, risk, etc.)
        document_content: Full document text
        depth: Review depth (quick, standard, thorough)
        registry_entry: Agent registry item with prompt_template and review_tool_schema

    Returns:
        Dict with findings, summary, and metrics
    """
    prompt_template = registry_entry.get('prompt_template', '')

    if not prompt_template:
        raise ValueError(f'No prompt_template in registry for agent: {agent_type}')

    # Generic tool spec — enforces base finding fields only. Agent-specific fields
    # (e.g., likelihood/consequence for risk) are driven by the prompt, not the schema.
    # This keeps the benchmark runner agent-agnostic: no changes needed when adding agents.
    tool_spec = {
        'toolSpec': {
            'name': 'submit_review',
            'description': f'Submit the {agent_type} review findings and summary.',
            'inputSchema': {
                'json': {
                    'type': 'object',
                    'required': ['findings', 'summary'],
                    'properties': {
                        'findings': {
                            'type': 'array',
                            'description': 'List of review findings',
                            'items': {
                                'type': 'object',
                                'required': ['id', 'severity', 'title',
                                             'description', 'recommendation'],
                                'properties': {
                                    'id': {'type': 'string'},
                                    'severity': {'type': 'string'},
                                    'title': {'type': 'string'},
                                    'description': {'type': 'string'},
                                    'recommendation': {'type': 'string'},
                                    'references': {'type': 'array', 'items': {'type': 'string'}},
                                },
                                'additionalProperties': True,
                            },
                        },
                        'summary': {'type': 'string', 'description': 'Overall assessment'},
                    },
                }
            },
        }
    }

    # Build organizational context (same as AgentCore agents do)
    org_context = 'No organizational context provided.'
    depth_instr = DEPTH_INSTRUCTIONS.get(depth, '')
    if depth_instr:
        org_context = depth_instr.strip()

    # Format the prompt template (same placeholders as agent prompt.md files)
    prompt_text = prompt_template.format(
        organizational_context=org_context,
        document_content=document_content,
    )

    start = time.time()
    response = bedrock.converse_stream(
        modelId=model_id,
        messages=[{'role': 'user', 'content': [{'text': prompt_text}]}],
        inferenceConfig={'temperature': 0.2},
        toolConfig={
            'tools': [tool_spec],
            'toolChoice': {'tool': {'name': 'submit_review'}},
        },
    )
    duration = time.time() - start

    # Assemble tool-use response from stream events
    findings_data = None
    tool_input_json = ''
    input_tokens = 0
    output_tokens = 0

    for event in response.get('stream', []):
        if 'contentBlockDelta' in event:
            delta = event['contentBlockDelta'].get('delta', {})
            if 'toolUse' in delta:
                tool_input_json += delta['toolUse'].get('input', '')
        elif 'metadata' in event:
            usage = event['metadata'].get('usage', {})
            input_tokens = usage.get('inputTokens', 0)
            output_tokens = usage.get('outputTokens', 0)

    duration = time.time() - start

    if tool_input_json:
        findings_data = json.loads(tool_input_json)

    if not findings_data:
        raise ValueError(f'Agent {agent_type} did not return tool-use response')

    # Extract metrics
    metrics = {
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
        'total_duration_s': round(duration, 2),
        'model_id': model_id,
    }

    return {
        'findings': findings_data.get('findings', []),
        'summary': findings_data.get('summary', ''),
        'metrics': metrics,
    }


def _invoke_judge(agent_type: str, findings: list, document_preview: str) -> tuple[dict, dict]:
    """Run the judge evaluator on findings. Returns quality scores."""
    findings_json = json.dumps(findings, indent=2)[:8000]
    prompt_text = JUDGE_PROMPT.format(
        agent_type=agent_type,
        document_preview=document_preview,
        findings_json=findings_json,
    )

    response = bedrock.converse(
        modelId=JUDGE_MODEL_ID,
        messages=[{'role': 'user', 'content': [{'text': prompt_text}]}],
        inferenceConfig={'maxTokens': 2048, 'temperature': 0.1},
        toolConfig={
            'tools': [JUDGE_TOOL],
            'toolChoice': {'tool': {'name': 'submit_evaluation'}},
        },
    )

    evaluation = None
    for block in response['output']['message']['content']:
        if 'toolUse' in block:
            evaluation = block['toolUse']['input']
            break

    if not evaluation:
        raise RuntimeError(
            f"Judge did not return tool use for {agent_type} "
            "— unexpected Bedrock response format"
        )

    # Normalize scores using shared logic (same truncation as invoke_judge.py)
    evaluation, overall, _ = normalize_evaluation(evaluation, quality_threshold=0.8)

    quality_scores = {
        'completeness': evaluation['scores_by_criterion']['completeness'],
        'specificity': evaluation['scores_by_criterion']['specificity'],
        'actionability': evaluation['scores_by_criterion']['actionability'],
        'overall': overall,
    }

    # Judge token metrics
    usage = response.get('usage', {})
    judge_metrics = {
        'input_tokens': usage.get('inputTokens', 0),
        'output_tokens': usage.get('outputTokens', 0),
    }

    return quality_scores, judge_metrics


def _run_single_config(
    config: dict, agent_type: str, registry_entry: dict,
    document_content: str, document_preview: str,
    benchmark_id: str, table,
) -> tuple[str, str]:
    """Run a single benchmark configuration: agent + judge + store."""
    config_id = config['config_id']
    depth = config.get('depth', 'standard')
    model_id = config['model_id']

    try:
        # 1. Invoke agent directly via Bedrock Converse (bypasses AgentCore
        #    so each config can use its own model_id)
        agent_result = _invoke_agent_direct(
            model_id, agent_type, document_content, depth, registry_entry,
        )

        # 2. Invoke judge
        quality_scores, judge_metrics = _invoke_judge(
            agent_type, agent_result['findings'], document_preview,
        )

        # Merge metrics
        metrics = agent_result['metrics']
        metrics['judge_input_tokens'] = judge_metrics['input_tokens']
        metrics['judge_output_tokens'] = judge_metrics['output_tokens']

        # 3. Store run result
        timestamp = datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds')
        item = {
            'PK': f'BENCHMARK#{benchmark_id}',
            'SK': f'RUN#{config_id}',
            'config_id': config_id,
            'status': 'completed',
            'findings': agent_result['findings'],
            'summary': agent_result['summary'],
            'quality_scores': quality_scores,
            'metrics': metrics,
            'completed_at': timestamp,
        }
        table.put_item(Item=convert_floats_to_decimal(item))

        logger.info(f"Config {config_id} completed: {len(agent_result['findings'])} findings, "
              f"quality={quality_scores['overall']:.2f}")
        return config_id, 'completed'

    except Exception as e:
        logger.error(f"Config {config_id} failed: {e}", exc_info=True)
        timestamp = datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds')
        table.put_item(Item={
            'PK': f'BENCHMARK#{benchmark_id}',
            'SK': f'RUN#{config_id}',
            'config_id': config_id,
            'status': 'failed',
            'error': str(e)[:500],
            'completed_at': timestamp,
        })
        return config_id, 'failed'


def lambda_handler(event: dict, context) -> dict:
    """Execute all benchmark configurations and update status.

    Invoked asynchronously by the API Lambda. Runs each configuration in
    parallel, stores per-config results, and updates the benchmark's overall
    status. A top-level try/except ensures the status is always set to
    'failed' with an error message if anything goes wrong before or during
    execution — preventing the benchmark from being stuck in 'running'
    indefinitely.

    Args:
        event: Benchmark payload with benchmark_id, agent_type, configurations,
               s3_bucket, s3_key, and document_project_id.
        context: Lambda context (unused).

    Returns:
        Dict with benchmark_id, final status, and per-config results.
    """
    benchmark_id = event['benchmark_id']
    table = dynamodb.Table(TABLE_NAME)

    try:
        agent_type = event['agent_type']
        configurations = event['configurations']
        s3_bucket = event['s3_bucket']
        s3_key = event['s3_key']

        logger.info(f"Starting benchmark {benchmark_id}: {len(configurations)} configs for {agent_type}")

        # Load document
        document_content = _load_document(s3_bucket, s3_key)
        document_preview = document_content[:2000]

        # Load agent registry (prompt template, tool schema)
        registry = load_agent_registry()
        registry_entry = registry.get(agent_type)
        if not registry_entry:
            raise ValueError(f'No registry entry found for agent type: {agent_type}')
        if not registry_entry.get('prompt_template'):
            raise ValueError(f'No prompt_template in registry for agent: {agent_type}. Run task deploy:seed.')

        # Run all configurations in parallel
        results = {}
        with ThreadPoolExecutor(max_workers=min(len(configurations), 5)) as executor:
            futures = {
                executor.submit(
                    _run_single_config, cfg, agent_type, registry_entry,
                    document_content, document_preview, benchmark_id, table,
                ): cfg['config_id']
                for cfg in configurations
            }
            for future in as_completed(futures):
                config_id = futures[future]
                try:
                    cid, status = future.result()
                    results[cid] = status
                except Exception as e:
                    results[config_id] = 'failed'
                    logger.error(f"Unexpected error for {config_id}: {e}")

        # Update benchmark status
        completed_count = sum(1 for s in results.values() if s == 'completed')
        if completed_count == len(results):
            final_status = 'completed'
        elif completed_count > 0:
            final_status = 'partial'
        else:
            final_status = 'failed'

        table.update_item(
            Key={'PK': f'BENCHMARK#{benchmark_id}', 'SK': 'METADATA'},
            UpdateExpression='SET #status = :s, updated_at = :ts',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={
                ':s': final_status,
                ':ts': datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds'),
            },
        )

        logger.info(f"Benchmark {benchmark_id} finished: {final_status} — {results}")
        return {'benchmark_id': benchmark_id, 'status': final_status, 'results': results}

    except Exception as e:
        logger.error(f"Benchmark {benchmark_id} failed at top level: {e}", exc_info=True)
        error_msg = str(e)[:500]
        try:
            table.update_item(
                Key={'PK': f'BENCHMARK#{benchmark_id}', 'SK': 'METADATA'},
                UpdateExpression='SET #status = :s, updated_at = :ts, error_message = :err',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':s': 'failed',
                    ':ts': datetime.now(tz=timezone.utc).isoformat(timespec='milliseconds'),
                    ':err': error_msg,
                },
            )
        except Exception as db_err:
            logger.error(f"Failed to update benchmark status after error: {db_err}", exc_info=True)
        raise
