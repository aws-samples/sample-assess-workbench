"""
Load Document Lambda — Reads documents + context from S3, project info from DynamoDB.
First step in the review workflow.

Supports multiple files per project, PDF text extraction via PyMuPDF,
and intelligent image analysis via Bedrock Converse (two-pass: triage + deep analysis).
Sends granular WebSocket progress events for the document processing and image analysis nodes.
"""
import logging
import os
import time
from pathlib import PurePosixPath
import boto3

from core.progress import send_progress, set_user_sub, set_review_context
from core.s3 import read_text, write_json, head_object, read_bytes
from core.projects import get_project, get_context_metadata
from core.doc_processing import (
    extract_text_and_images_from_pdf,
    prepare_image_for_bedrock,
    inject_image_analyses,
)

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    'required': ['project_id', 's3_bucket', 'files'],
    'optional': ['review_id', 's3_key', 'connection_id', 'user_sub', 'websocket_endpoint'],
}

dynamodb = boto3.resource('dynamodb')
bedrock = boto3.client('bedrock-runtime')

DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
if not DYNAMODB_TABLE_NAME:
    raise RuntimeError(
        'DYNAMODB_TABLE_NAME environment variable is required but not set. '
        'Check the Lambda configuration.'
    )
WEBSOCKET_API_ENDPOINT = os.environ.get('WEBSOCKET_API_ENDPOINT', '')
IMAGE_ANALYSIS_MODEL_ID = os.environ.get('IMAGE_ANALYSIS_MODEL_ID', 'us.anthropic.claude-sonnet-4-6')

# Supported text file extensions (decoded as UTF-8)
TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.rst', '.csv', '.json', '.yaml', '.yml'}

# File size limit — reject files larger than this to prevent Lambda OOM
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50MB per file
MAX_IMAGES_PER_DOCUMENT = 50
IMAGE_ANALYSIS_TIMEOUT_S = 150  # Leave 30s buffer for Lambda timeout

# Categories considered architecturally relevant
RELEVANT_CATEGORIES = {
    'architecture_diagram', 'sequence_diagram', 'flowchart',
    'uml', 'network_diagram', 'data_flow', 'er_diagram',
}

# --- Triage tool schema (forced via toolChoice) ---
CLASSIFY_IMAGE_TOOL = {
    'toolSpec': {
        'name': 'classify_image',
        'description': 'Classify a technical document image as relevant or irrelevant for architecture review.',
        'inputSchema': {
            'json': {
                'type': 'object',
                'required': ['category', 'relevant', 'confidence', 'brief_description'],
                'properties': {
                    'category': {
                        'type': 'string',
                        'enum': [
                            'architecture_diagram', 'sequence_diagram', 'flowchart',
                            'uml', 'network_diagram', 'data_flow', 'er_diagram',
                            'logo', 'decorative', 'screenshot', 'photo', 'other',
                        ],
                    },
                    'relevant': {'type': 'boolean', 'description': 'true if this image contains technical/architectural content worth analyzing'},
                    'confidence': {'type': 'number', 'description': '0.0 to 1.0 confidence in the classification'},
                    'brief_description': {'type': 'string', 'description': 'One-sentence description of what the image shows'},
                },
            }
        },
    }
}

TRIAGE_PROMPT = """Classify this image from a technical document. Return the classification by calling the classify_image tool.

Categories:
- architecture_diagram: System architecture, infrastructure, cloud service diagrams
- sequence_diagram: Sequence flows, interaction diagrams
- flowchart: Process flows, decision trees, workflow diagrams
- uml: Class diagrams, component diagrams, deployment diagrams, state machines
- network_diagram: Network topologies, VPC layouts, connectivity diagrams
- data_flow: Data pipeline diagrams, ETL flows, event streaming diagrams
- er_diagram: Entity-relationship diagrams, database schemas
- logo: Company logos, product logos, brand marks
- decorative: Headers, banners, backgrounds, icons, stock imagery
- screenshot: UI screenshots, terminal output, code screenshots
- photo: Photographs of people, places, objects
- other: Anything that doesn't fit the above categories"""

# --- Deep analysis tool schema ---
DESCRIBE_DIAGRAM_TOOL = {
    'toolSpec': {
        'name': 'describe_diagram',
        'description': 'Extract structured architectural information from a technical diagram.',
        'inputSchema': {
            'json': {
                'type': 'object',
                'required': ['diagram_type', 'summary', 'components', 'connections', 'description'],
                'properties': {
                    'diagram_type': {'type': 'string'},
                    'summary': {'type': 'string', 'description': '2-3 sentence summary of what the diagram shows'},
                    'components': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'type': {'type': 'string', 'description': 'e.g. AWS Lambda, database, microservice, load balancer'},
                                'details': {'type': 'string'},
                            },
                        },
                    },
                    'connections': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'from': {'type': 'string'},
                                'to': {'type': 'string'},
                                'label': {'type': 'string'},
                                'direction': {'type': 'string', 'enum': ['unidirectional', 'bidirectional']},
                            },
                        },
                    },
                    'groupings': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'type': {'type': 'string'},
                                'contains': {'type': 'array', 'items': {'type': 'string'}},
                            },
                        },
                    },
                    'sequence_steps': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Ordered steps if this is a sequence/flow diagram',
                    },
                    'technologies': {'type': 'array', 'items': {'type': 'string'}},
                    'security_elements': {'type': 'array', 'items': {'type': 'string'}},
                    'description': {
                        'type': 'string',
                        'description': 'Full natural language description of the diagram suitable for an architecture reviewer',
                    },
                },
            }
        },
    }
}

ANALYSIS_PROMPT = """You are analyzing a technical diagram from an architecture document. Extract all meaningful technical information from this image.

Identify and describe:
1. Components/Nodes: List every component, service, or system shown. For AWS services, use the official service name.
2. Connections/Flows: Describe each connection — what data or requests flow, direction, protocols or formats.
3. Groupings: Identify logical groupings (VPCs, subnets, AZs, accounts, regions, bounded contexts).
4. Sequence/Ordering: If the diagram shows a sequence or process flow, describe the steps in order.
5. Labels & Annotations: Capture all text labels, annotations, legends, and notes.
6. Technology Stack: List specific technologies, frameworks, databases, or services.
7. Security Boundaries: Note security-relevant elements (firewalls, WAFs, encryption, auth flows, trust boundaries).
8. Data Stores: Identify databases, caches, queues, and storage systems with their types.

Be thorough and precise. The review agents will use your description as a substitute for seeing the diagram directly.

Call the describe_diagram tool with your analysis."""


def call_bedrock_converse(
    image_bytes: bytes,
    image_format: str,
    prompt: str,
    tool: dict,
    max_tokens: int = 1024,
) -> tuple[dict | None, dict]:
    """Make a Bedrock Converse call with an image and forced tool use.

    Returns (tool_result_dict, usage_dict) or (None, {}) on failure.
    """
    try:
        response = bedrock.converse(
            modelId=IMAGE_ANALYSIS_MODEL_ID,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'image': {
                            'format': image_format,
                            'source': {'bytes': image_bytes},
                        }
                    },
                    {'text': prompt},
                ],
            }],
            inferenceConfig={'maxTokens': max_tokens, 'temperature': 0.1},
            toolConfig={
                'tools': [tool],
                'toolChoice': {'tool': {'name': tool['toolSpec']['name']}},
            },
        )

        usage = response.get('usage', {})
        usage_out = {
            'input': usage.get('inputTokens', 0),
            'output': usage.get('outputTokens', 0),
        }

        # Extract tool use result
        for block in response['output']['message']['content']:
            if 'toolUse' in block:
                return block['toolUse']['input'], usage_out

        return None, usage_out
    except Exception as e:
        logger.error(f"Bedrock Converse error: {e}", exc_info=True)
        return None, {}


def analyze_images(
    images: list[dict],
    connection_id: str,
    websocket_endpoint: str,
) -> tuple[list[dict], dict]:
    """Two-pass image analysis using Bedrock Converse.

    Pass 1 (triage): Classify each image as relevant or not.
    Pass 2 (deep analysis): Extract architectural detail from relevant images.

    Returns:
        tuple: (analysis_results, metrics)
        - analysis_results: list of dicts with page_num, image_index, and either
          'analysis' (for relevant) or 'skipped_reason' (for irrelevant)
        - metrics: dict with token counts and summary stats
    """
    if not images:
        return [], {}

    # Cap at max images
    if len(images) > MAX_IMAGES_PER_DOCUMENT:
        logger.warning(f" {len(images)} images found, capping at {MAX_IMAGES_PER_DOCUMENT}")
        overflow = images[MAX_IMAGES_PER_DOCUMENT:]
        images = images[:MAX_IMAGES_PER_DOCUMENT]
    else:
        overflow = []

    total = len(images)
    filenames = list(set(img.get('filename', '') for img in images if img.get('filename')))

    send_progress(connection_id, websocket_endpoint, 'image_analysis_started', {
        'total_images': total + len(overflow),
        'filenames': filenames,
    })

    metrics = {
        'total_images': total + len(overflow),
        'images_analyzed': 0,
        'images_skipped': 0,
        'triage_tokens': {'input': 0, 'output': 0},
        'analysis_tokens': {'input': 0, 'output': 0},
        'total_tokens': 0,
        'per_image': [],
    }

    results = []
    start_time = time.time()

    for idx, img_info in enumerate(images):
        elapsed = time.time() - start_time
        if elapsed > IMAGE_ANALYSIS_TIMEOUT_S:
            remaining = total - idx + len(overflow)
            logger.warning(f"Image analysis timeout after {elapsed:.1f}s — {remaining} images not processed")
            results.append({
                'type': 'timeout',
                'message': f'[Remaining {remaining} images not analyzed — timeout]',
            })
            break

        filename = img_info.get('filename', '')
        page_num = img_info['page_num']
        image_index = img_info['image_index']

        # Prepare image for Bedrock
        prepared_bytes, prepared_format = prepare_image_for_bedrock(img_info)
        if not prepared_bytes:
            logger.info(f"Skipping unprocessable image: page {page_num}, index {image_index}")
            metrics['images_skipped'] += 1
            continue

        # --- Pass 1: Triage ---
        send_progress(connection_id, websocket_endpoint, 'image_triage_started', {
            'filename': filename, 'page_num': page_num, 'image_index': image_index,
            'index': idx + 1, 'total': total,
        })

        triage_result, triage_usage = call_bedrock_converse(
            prepared_bytes, prepared_format, TRIAGE_PROMPT, CLASSIFY_IMAGE_TOOL, max_tokens=512,
        )

        metrics['triage_tokens']['input'] += triage_usage.get('input', 0)
        metrics['triage_tokens']['output'] += triage_usage.get('output', 0)

        if not triage_result:
            logger.warning(f"Triage failed for page {page_num}, image {image_index} — skipping")
            metrics['images_skipped'] += 1
            send_progress(connection_id, websocket_endpoint, 'image_skipped', {
                'filename': filename, 'page_num': page_num, 'image_index': image_index,
                'category': 'unknown', 'reason': 'Triage call failed',
            })
            continue

        category = triage_result.get('category', 'other')
        relevant = triage_result.get('relevant', False)
        confidence = triage_result.get('confidence', 0)
        brief_desc = triage_result.get('brief_description', '')

        send_progress(connection_id, websocket_endpoint, 'image_classified', {
            'filename': filename, 'page_num': page_num, 'image_index': image_index,
            'category': category, 'relevant': relevant, 'confidence': confidence,
            'brief_description': brief_desc,
            'triage_tokens': triage_usage,
        })

        img_metrics = {
            'page_num': page_num, 'image_index': image_index, 'filename': filename,
            'category': category, 'relevant': relevant, 'triage_tokens': triage_usage,
        }

        if not relevant or category not in RELEVANT_CATEGORIES:
            metrics['images_skipped'] += 1
            img_metrics['status'] = 'skipped'
            metrics['per_image'].append(img_metrics)
            results.append({
                'type': 'skipped',
                'page_num': page_num, 'image_index': image_index, 'filename': filename,
                'category': category, 'brief_description': brief_desc,
            })
            send_progress(connection_id, websocket_endpoint, 'image_skipped', {
                'filename': filename, 'page_num': page_num, 'image_index': image_index,
                'category': category, 'reason': 'Not architecturally relevant',
            })
            continue

        # --- Pass 2: Deep Analysis ---
        send_progress(connection_id, websocket_endpoint, 'image_analysis_in_progress', {
            'filename': filename, 'page_num': page_num, 'image_index': image_index,
            'category': category,
        })

        analysis_result, analysis_usage = call_bedrock_converse(
            prepared_bytes, prepared_format, ANALYSIS_PROMPT, DESCRIBE_DIAGRAM_TOOL, max_tokens=4096,
        )

        metrics['analysis_tokens']['input'] += analysis_usage.get('input', 0)
        metrics['analysis_tokens']['output'] += analysis_usage.get('output', 0)

        if not analysis_result:
            logger.warning(f"Deep analysis failed for page {page_num}, image {image_index}")
            metrics['images_skipped'] += 1
            img_metrics['status'] = 'analysis_failed'
            metrics['per_image'].append(img_metrics)
            results.append({
                'type': 'analysis_failed',
                'page_num': page_num, 'image_index': image_index, 'filename': filename,
                'category': category,
            })
            continue

        metrics['images_analyzed'] += 1
        img_metrics['status'] = 'analyzed'
        img_metrics['analysis_tokens'] = analysis_usage
        metrics['per_image'].append(img_metrics)

        component_count = len(analysis_result.get('components', []))
        connection_count = len(analysis_result.get('connections', []))

        send_progress(connection_id, websocket_endpoint, 'image_analyzed', {
            'filename': filename, 'page_num': page_num, 'image_index': image_index,
            'diagram_type': analysis_result.get('diagram_type', category),
            'component_count': component_count,
            'connection_count': connection_count,
            'analysis_tokens': analysis_usage,
        })

        results.append({
            'type': 'analyzed',
            'page_num': page_num, 'image_index': image_index, 'filename': filename,
            'category': category, 'analysis': analysis_result,
        })

    # Handle overflow images
    for img_info in overflow:
        results.append({
            'type': 'skipped',
            'page_num': img_info['page_num'], 'image_index': img_info['image_index'],
            'filename': img_info.get('filename', ''),
            'category': 'overflow', 'brief_description': 'Exceeded max image limit',
        })
        metrics['images_skipped'] += 1

    # Compute totals
    duration_ms = int((time.time() - start_time) * 1000)
    metrics['total_tokens'] = (
        metrics['triage_tokens']['input'] + metrics['triage_tokens']['output']
        + metrics['analysis_tokens']['input'] + metrics['analysis_tokens']['output']
    )
    metrics['duration_ms'] = duration_ms

    send_progress(connection_id, websocket_endpoint, 'image_analysis_completed', {
        'total_images': metrics['total_images'],
        'analyzed': metrics['images_analyzed'],
        'skipped': metrics['images_skipped'],
        'total_tokens': metrics['total_tokens'],
        'duration_ms': duration_ms,
    })

    return results, metrics


def _process_file(
    s3_bucket: str, file_s3_key: str, filename: str, ext: str,
) -> dict:
    """Read a single file from S3 and extract text content.

    Returns (text, pages, images, size_kb) or None if the file was skipped
    due to size limits. When skipped, returns a dict with skip info instead.
    """
    head = head_object(s3_bucket, file_s3_key)
    content_length = head.get('ContentLength', 0)

    if content_length > MAX_FILE_BYTES:
        size_mb = round(content_length / (1024 * 1024), 1)
        limit_mb = round(MAX_FILE_BYTES / (1024 * 1024))
        return {
            'skipped': True,
            'reason': 'too_large',
            'size_mb': size_mb,
            'limit_mb': limit_mb,
            'size_kb': round(content_length / 1024, 1),
        }

    raw_bytes = read_bytes(s3_bucket, file_s3_key)
    file_size_kb = round(len(raw_bytes) / 1024, 1)

    file_text = ''
    file_pages = 0
    images = []

    if ext == '.pdf':
        file_text, file_pages, images = extract_text_and_images_from_pdf(raw_bytes)
        for img in images:
            img['filename'] = filename
    elif ext in TEXT_EXTENSIONS or ext == '':
        try:
            file_text = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            file_text = raw_bytes.decode('utf-8', errors='replace')
    else:
        file_text = f'[Binary file: {filename} — content not extracted]'

    return {
        'skipped': False,
        'text': file_text,
        'pages': file_pages,
        'images': images,
        'size_kb': file_size_kb,
    }


def _load_project_context(
    project_id: str, connection_id: str, websocket_endpoint: str,
) -> tuple[dict, str]:
    """Load project metadata and organizational context from DynamoDB/S3.

    Args:
        project_id: Project identifier.
        connection_id: WebSocket connection ID for progress events.
        websocket_endpoint: WebSocket API endpoint URL.

    Returns:
        Tuple of (project_info dict, organizational_context string).
    """
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    project_info = get_project(table, project_id) or {}

    organizational_context = ''
    context_id = project_info.get('context_id', '')
    if context_id:
        ctx_meta = get_context_metadata(table, context_id)
        if ctx_meta and ctx_meta.get('s3_bucket') and ctx_meta.get('s3_key'):
            organizational_context = read_text(
                ctx_meta['s3_bucket'], ctx_meta['s3_key']
            )
            send_progress(connection_id, websocket_endpoint, 'context_s3_read', {
                'context_id': context_id,
            })

    return project_info, organizational_context


def lambda_handler(event: dict, context) -> dict:
    project_id = event['project_id']
    s3_bucket = event['s3_bucket']
    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '') or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get('user_sub', ''))
    set_review_context(event.get('project_id', ''), event.get('review_id', ''))

    files = event.get('files', [])
    if not files:
        raise ValueError(
            'No files provided in event payload. '
            'The "files" array is required with at least one entry.'
        )

    total_files = len(files)
    send_progress(connection_id, websocket_endpoint, 'document_processing_started', {
        'total_files': total_files,
    })

    combined_sections = []
    total_pages = 0
    total_images = 0
    total_size_kb = 0
    file_summaries = []
    all_images = []

    for idx, file_info in enumerate(files):
        file_s3_key = file_info['s3_key']
        filename = file_info.get('filename', file_s3_key.rsplit('/', 1)[-1])
        ext = PurePosixPath(filename).suffix.lower()

        send_progress(connection_id, websocket_endpoint, 'file_processing_started', {
            'filename': filename,
            'file_type': ext.lstrip('.') or 'unknown',
            'index': idx + 1,
            'total_files': total_files,
        })

        result = _process_file(s3_bucket, file_s3_key, filename, ext)

        if result['skipped']:
            send_progress(connection_id, websocket_endpoint, 'file_processing_started', {
                'filename': filename,
                'file_type': ext.lstrip('.') or 'unknown',
                'index': idx + 1,
                'total_files': total_files,
                'error': f"File too large ({result['size_mb']}MB, limit {result['limit_mb']}MB) — skipped",
            })
            combined_sections.append({'filename': filename, 'text': f"[Skipped: {filename} — {result['size_mb']}MB exceeds {result['limit_mb']}MB limit]"})
            file_summaries.append({
                'filename': filename, 'type': ext.lstrip('.') or 'text',
                'pages': 0, 'images': 0, 'size_kb': result['size_kb'],
                'skipped': True, 'reason': 'too_large',
            })
            continue

        total_size_kb += result['size_kb']
        total_pages += result['pages']
        total_images += len(result['images'])
        all_images.extend(result['images'])

        send_progress(connection_id, websocket_endpoint, 'file_text_extracted', {
            'filename': filename,
            'file_type': ext.lstrip('.') or 'text',
            'pages': result['pages'],
            'images': len(result['images']),
            'size_kb': result['size_kb'],
            'index': idx + 1,
            'total_files': total_files,
        })

        section = f"--- File: {filename} ---\n\n{result['text']}" if total_files > 1 else result['text']
        combined_sections.append({'filename': filename, 'text': section})
        file_summaries.append({
            'filename': filename,
            'type': ext.lstrip('.') or 'text',
            'pages': result['pages'],
            'images': len(result['images']),
            'size_kb': result['size_kb'],
        })

    send_progress(connection_id, websocket_endpoint, 'all_files_processed', {
        'total_files': total_files,
        'total_pages': total_pages,
        'total_images': total_images,
        'combined_size_kb': round(total_size_kb, 1),
        'files': file_summaries,
    })

    # --- Image Analysis (Phase 2) ---
    image_analysis_results = []
    image_analysis_metrics = {}
    if all_images:
        image_analysis_results, image_analysis_metrics = analyze_images(
            all_images, connection_id, websocket_endpoint,
        )
        for section in combined_sections:
            section['text'] = inject_image_analyses(
                section['text'], image_analysis_results, filename=section['filename'],
            )

    document_content = "\n\n".join(s['text'] for s in combined_sections)
    doc_size_kb = round(len(document_content.encode('utf-8')) / 1024, 1)

    project_info, organizational_context = _load_project_context(
        project_id, connection_id, websocket_endpoint,
    )

    send_progress(connection_id, websocket_endpoint, 'document_loaded', {
        'size_kb': doc_size_kb,
        'total_files': total_files,
        'total_pages': total_pages,
        'total_images': total_images,
        'images_analyzed': image_analysis_metrics.get('images_analyzed', 0),
        'images_skipped': image_analysis_metrics.get('images_skipped', 0),
        'image_analysis_tokens': image_analysis_metrics.get('total_tokens', 0),
    })

    # Store combined document content in S3 as JSON to avoid carrying it
    # through the Step Functions state machine (256KB payload limit).
    document_s3_key = f"projects/{project_id}/reviews/{event['review_id']}/document.json"
    document_data = {
        'document_content': document_content,
        'organizational_context': organizational_context,
    }
    write_json(s3_bucket, document_s3_key, document_data)
    logger.info(f"Stored document content in S3: {document_s3_key}")

    # Return only fields that the state machine's Assign block extracts.
    # Context fields (project_id, s3_bucket, etc.) are already in workflow
    # variables from InitWorkflow — no need to echo them back.
    return {
        'document_s3_key': document_s3_key,
        'project_name': project_info.get('name', 'Unknown Project'),
        'project_description': project_info.get('description', ''),
        'image_analysis_metrics': {
            'total_tokens': image_analysis_metrics.get('total_tokens', 0),
            'images_analyzed': image_analysis_metrics.get('images_analyzed', 0),
            'images_skipped': image_analysis_metrics.get('images_skipped', 0),
            'duration_ms': image_analysis_metrics.get('duration_ms', 0),
        } if image_analysis_metrics else {},
    }
