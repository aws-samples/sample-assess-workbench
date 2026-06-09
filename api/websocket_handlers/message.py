"""WebSocket message handler with streaming support.

Dispatches incoming WebSocket actions to dedicated handlers:
- sendMessage: Chat with an agent (streaming response)
- listChatSessions: List sessions for a project+agent
- createChatSession: Create a new chat session
- deleteChatSession: Delete a session and its messages
- loadChatHistory: Load messages for a specific session
"""
import json
import os
import time
import uuid
import boto3
import logging

from core.registry import load_agent_arns
from core.s3 import read_text
from core.chat import (
    create_chat_session,
    delete_chat_session,
    list_chat_sessions,
    load_chat_history,
    load_chat_messages,
    store_chat_message,
    update_session_metadata,
)
from core.projects import get_project, get_context_metadata

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# AWS clients
dynamodb = boto3.resource('dynamodb')
projects_table = dynamodb.Table(os.environ['PROJECTS_TABLE'])

# Connections table — used to resolve user_sub from connectionId
_connections_table_name = os.environ.get('CONNECTIONS_TABLE', '')
connections_table = (
    dynamodb.Table(_connections_table_name) if _connections_table_name else None
)

# Shared memory ARN
SHARED_MEMORY_ARN = os.environ.get('SHARED_MEMORY_ARN', '')

# Knowledge Base IDs — set by Terraform, empty when not deployed.
DOCUMENT_KB_ID = os.environ.get('DOCUMENT_KB_ID', '')
STANDARDS_KB_ID = os.environ.get('STANDARDS_KB_ID', '')

# Max chat message length (characters) — prevents token cost abuse
MAX_MESSAGE_LENGTH = 10_000


def _get_chat_agent_arns():
    """Load chat agent ARNs via shared registry module."""
    return load_agent_arns(role='chat')


# Cache for API Gateway management client (one per endpoint per invocation)
_apigw_clients = {}


def _get_apigw_client(endpoint_url):
    """Get or create a cached API Gateway management client."""
    if endpoint_url not in _apigw_clients:
        _apigw_clients[endpoint_url] = boto3.client(
            'apigatewaymanagementapi', endpoint_url=endpoint_url
        )
    return _apigw_clients[endpoint_url]


def send_to_connection(connection_id, endpoint_url, data):
    """Send data to WebSocket connection."""
    try:
        client = _get_apigw_client(endpoint_url)
        client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(data, default=str).encode('utf-8')
        )
        return True
    except client.exceptions.GoneException:
        logger.warning(f"Connection {connection_id} is gone")
        return False
    except Exception as e:
        logger.error(f"Error sending to connection {connection_id}: {str(e)}")
        return False


def _get_user_sub_for_connection(connection_id: str) -> str:
    """Look up the user_sub stored at connect time for this connection.

    Args:
        connection_id: WebSocket connection ID.

    Returns:
        user_sub string, or empty string if the connections table is not
        configured or the connection record is not found.
    """
    if not connections_table:
        logger.warning("CONNECTIONS_TABLE not configured — cannot resolve user identity")
        return ''
    try:
        response = connections_table.get_item(Key={'connectionId': connection_id})
        item = response.get('Item')
        if not item:
            logger.warning(f"No connection record found for {connection_id}")
            return ''
        return item.get('userSub', '')
    except Exception as e:
        logger.error(f"Failed to look up connection {connection_id}: {e}")
        return ''


def _verify_project_access(project_id: str, user_sub: str) -> bool:
    """Check that the project exists and the user is authenticated.

    Any authenticated user (verified at WebSocket $connect by the JWT
    authorizer) may chat on any project. Write-level access control
    (trigger review, approve, delete) is enforced by the REST API layer,
    not the chat handler.

    Args:
        project_id: Project identifier.
        user_sub: Cognito user sub resolved from the connection record.

    Returns:
        True if access is permitted, False otherwise.
    """
    if not user_sub:
        # No identity resolved — deny access
        return False
    project = get_project(projects_table, project_id)
    if not project:
        return False
    return True


def build_agent_payload(
    project_id: str,
    user_sub: str,
    agent: str,
    session_id: str,
    user_message: str,
    connection_id: str = '',
    endpoint_url: str = '',
) -> dict | None:
    """Build payload for chat agent invocation.

    The agent receives memory coordinates (``shared_memory_id``,
    ``project_id``, ``agent_type``) and uses its ``search_findings``
    tool to query memory on demand. No pre-fetched findings.

    Args:
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the chat session (used to
            scope chat-history retrieval to this user).
        agent: Agent type key (e.g. 'cri_review', 'security').
        session_id: Chat session identifier for scoped history.
        user_message: The user's chat message.
        connection_id: WebSocket connection ID for warning events.
        endpoint_url: WebSocket management endpoint for warning events.

    Returns:
        Payload dict for the chat agent, or None if the project doesn't exist.
    """
    project = get_project(projects_table, project_id)

    if not project:
        return None

    shared_memory_id = ''
    if SHARED_MEMORY_ARN:
        if '/' not in SHARED_MEMORY_ARN:
            raise ValueError(
                f"Malformed SHARED_MEMORY_ARN — expected format "
                f"'arn:aws:bedrock-agentcore:region:account:memory/ID', "
                f"got: {SHARED_MEMORY_ARN!r}"
            )
        shared_memory_id = SHARED_MEMORY_ARN.split('/')[-1]
    else:
        logger.info("SHARED_MEMORY_ARN not configured — memory retrieval disabled")

    organizational_context = "No organizational context provided."
    context_id = project.get('context_id', '')
    if context_id:
        try:
            ctx_meta = get_context_metadata(projects_table, context_id)
            if ctx_meta and ctx_meta.get('s3_bucket') and ctx_meta.get('s3_key'):
                organizational_context = read_text(
                    ctx_meta['s3_bucket'], ctx_meta['s3_key']
                )
        except Exception as e:
            logger.error(f"Failed to load context document for context_id={context_id}: {e}")
            organizational_context = (
                "[CONTEXT_UNAVAILABLE] Failed to load organizational context — "
                "S3 error. Responses may lack organizational context."
            )
            send_to_connection(connection_id, endpoint_url, {
                'type': 'chat_warning',
                'warning': 'Organizational context unavailable',
            })

    # Determine document_kb_id — only include when the project has an
    # indexed document. The project's document_indexed flag is set by
    # the IndexDocument workflow step on successful indexing.
    document_kb_id = ""
    if DOCUMENT_KB_ID and project.get("document_indexed"):
        document_kb_id = DOCUMENT_KB_ID

    standards_kb_id = STANDARDS_KB_ID

    send_to_connection(connection_id, endpoint_url, {
        'type': 'chat_capabilities',
        'has_findings': bool(shared_memory_id),
        'has_document_search': bool(document_kb_id),
        'has_standards_lookup': bool(standards_kb_id),
        'agent': agent,
    })

    return {
        'question': user_message,
        'project_id': project_id,
        'user_sub': user_sub,
        'project_name': project.get('name', 'Unknown Project'),
        'project_description': project.get('description', ''),
        'shared_memory_id': shared_memory_id,
        'agent_type': agent,
        'organizational_context': organizational_context,
        'chat_history': load_chat_history(
            projects_table, project_id, user_sub, agent, session_id
        ),
        'participating_agents': project.get('participating_agents', ''),
        'document_kb_id': document_kb_id,
        'standards_kb_id': standards_kb_id,
    }


# ── Action handlers ──────────────────────────────────────────────────


def handle_list_sessions(body, connection_id, endpoint_url, user_sub: str = ''):
    """Handle listChatSessions — return all sessions for a project+agent.

    Args:
        body: Parsed WebSocket message body.
        connection_id: WebSocket connection ID.
        endpoint_url: API Gateway management endpoint.
        user_sub: Cognito user sub resolved from the connection record.

    Returns:
        Lambda response dict.
    """
    project_id = body.get('projectId')
    agent = body.get('agent')

    if not project_id or not agent:
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Missing required fields: projectId, agent',
        })
        return {'statusCode': 400}

    if not _verify_project_access(project_id, user_sub):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Access denied',
        })
        return {'statusCode': 403}

    sessions = list_chat_sessions(projects_table, project_id, user_sub, agent)
    send_to_connection(connection_id, endpoint_url, {
        'type': 'chat_sessions',
        'agent': agent,
        'sessions': sessions,
    })
    return {'statusCode': 200}


def handle_create_session(body, connection_id, endpoint_url, user_sub: str = ''):
    """Handle createChatSession — create a new session.

    Args:
        body: Parsed WebSocket message body.
        connection_id: WebSocket connection ID.
        endpoint_url: API Gateway management endpoint.
        user_sub: Cognito user sub resolved from the connection record.

    Returns:
        Lambda response dict.
    """
    project_id = body.get('projectId')
    agent = body.get('agent')
    title = body.get('title', 'New conversation')

    if not project_id or not agent:
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Missing required fields: projectId, agent',
        })
        return {'statusCode': 400}

    if not _verify_project_access(project_id, user_sub):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Access denied',
        })
        return {'statusCode': 403}

    session = create_chat_session(projects_table, project_id, user_sub, agent, title)
    send_to_connection(connection_id, endpoint_url, {
        'type': 'chat_session_created',
        'agent': agent,
        'session': session,
    })
    return {'statusCode': 200}


def handle_delete_session(body, connection_id, endpoint_url, user_sub: str = ''):
    """Handle deleteChatSession — delete a session and its messages.

    Args:
        body: Parsed WebSocket message body.
        connection_id: WebSocket connection ID.
        endpoint_url: API Gateway management endpoint.
        user_sub: Cognito user sub resolved from the connection record.

    Returns:
        Lambda response dict.
    """
    project_id = body.get('projectId')
    agent = body.get('agent')
    session_id = body.get('sessionId')

    if not all([project_id, agent, session_id]):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Missing required fields: projectId, agent, sessionId',
        })
        return {'statusCode': 400}

    if not _verify_project_access(project_id, user_sub):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Access denied',
        })
        return {'statusCode': 403}

    items_deleted = delete_chat_session(
        projects_table, project_id, user_sub, agent, session_id
    )
    send_to_connection(connection_id, endpoint_url, {
        'type': 'chat_session_deleted',
        'agent': agent,
        'session_id': session_id,
        'items_deleted': items_deleted,
    })
    return {'statusCode': 200}


def handle_load_history(body, connection_id, endpoint_url, user_sub: str = ''):
    """Handle loadChatHistory — load messages for a specific session.

    Args:
        body: Parsed WebSocket message body.
        connection_id: WebSocket connection ID.
        endpoint_url: API Gateway management endpoint.
        user_sub: Cognito user sub resolved from the connection record.

    Returns:
        Lambda response dict.
    """
    project_id = body.get('projectId')
    agent = body.get('agent')
    session_id = body.get('sessionId')

    if not all([project_id, agent, session_id]):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Missing required fields: projectId, agent, sessionId',
        })
        return {'statusCode': 400}

    if not _verify_project_access(project_id, user_sub):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Access denied',
        })
        return {'statusCode': 403}

    messages = load_chat_messages(
        projects_table, project_id, user_sub, agent, session_id
    )
    send_to_connection(connection_id, endpoint_url, {
        'type': 'chat_history',
        'agent': agent,
        'session_id': session_id,
        'messages': messages,
    })
    return {'statusCode': 200}


def handle_send_message(body, connection_id, endpoint_url, user_sub: str = ''):
    """Handle sendMessage — invoke a chat agent with streaming response.

    Args:
        body: Parsed WebSocket message body.
        connection_id: WebSocket connection ID.
        endpoint_url: API Gateway management endpoint.
        user_sub: Cognito user sub resolved from the connection record.

    Returns:
        Lambda response dict.
    """
    project_id = body.get('projectId')
    agent = body.get('agent')
    message = body.get('message')
    session_id = body.get('sessionId')

    if not all([project_id, agent, message, session_id]):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Missing required fields: projectId, agent, message, sessionId',
        })
        return {'statusCode': 400}

    if len(message) > MAX_MESSAGE_LENGTH:
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': f'Message too long ({len(message)} chars, max {MAX_MESSAGE_LENGTH})',
        })
        return {'statusCode': 400}

    if not _verify_project_access(project_id, user_sub):
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Access denied',
        })
        return {'statusCode': 403}

    # Validate agent exists in registry
    try:
        chat_arns = _get_chat_agent_arns()
    except RuntimeError as e:
        logger.error(f"Agent registry unavailable: {e}")
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': 'Agent registry unavailable — please try again later',
        })
        return {'statusCode': 503}

    if agent not in chat_arns:
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': f'Invalid agent: {agent}. Valid agents: {", ".join(chat_arns.keys())}',
        })
        return {'statusCode': 400}

    # Build payload for chat agent
    payload = build_agent_payload(
        project_id, user_sub, agent, session_id, message, connection_id, endpoint_url
    )

    if not payload:
        send_to_connection(connection_id, endpoint_url, {
            'type': 'error',
            'error': f'Project {project_id} not found',
        })
        return {'statusCode': 404}

    # Invoke chat agent with streaming
    logger.info(f"Invoking {agent} chat agent for project {project_id}")

    agentcore_client = boto3.client('bedrock-agentcore')
    agent_arn = chat_arns[agent]

    # Generate runtime session ID (must be 33+ chars for AgentCore)
    # This is unrelated to our chat session concept
    runtime_session_id = f"{project_id}_{agent}_{str(uuid.uuid4())}"

    invoke_params = {
        'agentRuntimeArn': agent_arn,
        'runtimeSessionId': runtime_session_id,
        'payload': json.dumps(payload).encode('utf-8'),
    }

    response = agentcore_client.invoke_agent_runtime(**invoke_params)

    # Process SSE streaming response from AgentCore
    full_response = ""
    response_body = response.get('response')
    content_type = response.get('contentType', '')

    logger.info(f"Response contentType: {content_type}")

    stream_start = time.time()
    chunk_count = 0

    apigw_client = _get_apigw_client(endpoint_url)

    def send_chunk(text):
        """Send a text chunk to the WebSocket client."""
        try:
            apigw_client.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(
                    {'type': 'chunk', 'agent': agent, 'content': text},
                    default=str,
                ).encode('utf-8'),
            )
        except apigw_client.exceptions.GoneException:
            logger.warning(f"Connection {connection_id} is gone")
        except Exception as e:
            logger.error(f"Error sending chunk: {e}")

    if "text/event-stream" in content_type:
        logger.info("Processing SSE event stream")
        for line in response_body.iter_lines(chunk_size=10):
            if line:
                decoded = line.decode('utf-8') if isinstance(line, bytes) else line
                if decoded.startswith('data: '):
                    data_str = decoded[6:]
                    chunk_count += 1
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        data = data_str

                    # Typed metadata events: the agent can yield JSON
                    # objects with a "type" field to send structured
                    # events (e.g. usage metrics) alongside the text
                    # stream. Route these as separate WebSocket events
                    # instead of text chunks.
                    if isinstance(data, dict) and "type" in data:
                        data["agent"] = agent
                        send_to_connection(
                            connection_id, endpoint_url, data
                        )
                        continue

                    chunk_text = data if isinstance(data, str) else str(data)
                    full_response += chunk_text
                    elapsed = (time.time() - stream_start) * 1000
                    logger.info(
                        f"SSE #{chunk_count}: {len(chunk_text)} chars, "
                        f"elapsed {elapsed:.0f}ms"
                    )
                    send_chunk(chunk_text)

        logger.info(
            f"Streaming complete: {chunk_count} events, "
            f"{len(full_response)} total chars, "
            f"{(time.time() - stream_start)*1000:.0f}ms total"
        )

    elif hasattr(response_body, 'read'):
        logger.info("Processing non-SSE StreamingBody")
        content = []
        for chunk in response_body:
            content.append(
                chunk.decode('utf-8') if isinstance(chunk, bytes) else str(chunk)
            )
        full_response = ''.join(content)
        send_chunk(full_response)

    elif isinstance(response_body, (bytes, str)):
        full_response = (
            response_body.decode('utf-8')
            if isinstance(response_body, bytes)
            else response_body
        )
        send_chunk(full_response)

    else:
        logger.warning(f"Unexpected response type: {type(response_body)}")
        full_response = str(response_body)
        send_chunk(full_response)

    # Send completion
    send_to_connection(connection_id, endpoint_url, {
        'type': 'complete',
        'agent': agent,
        'fullResponse': full_response,
    })

    # Store messages in DynamoDB — skip blocked turns so the offending
    # content doesn't pollute chat history and re-trigger the guardrail.
    # Blocked interactions are captured in the guardrail events table instead.
    _GUARDRAIL_BLOCKED_MESSAGES = {
        "Your input was blocked by our content policy.",
        "The response was blocked by our content policy.",
    }
    if full_response.strip() not in _GUARDRAIL_BLOCKED_MESSAGES:
        store_chat_message(
            projects_table, project_id, user_sub, agent, session_id, message, full_response
        )

    # Update session metadata (title on first message, updated_at, count)
    # Separate from store_chat_message so a metadata failure doesn't lose messages
    try:
        title_update = update_session_metadata(
            projects_table, project_id, user_sub, agent, session_id, message
        )
        # Push updated title to the client so the session list reflects it
        if title_update:
            send_to_connection(connection_id, endpoint_url, {
                'type': 'chat_session_updated',
                'agent': agent,
                'session_id': title_update['session_id'],
                'title': title_update['title'],
            })
    except Exception as e:
        logger.error(
            f"Failed to update session metadata for session {session_id}: {e}"
        )

    logger.info(f"Successfully processed message for {agent} agent")
    return {'statusCode': 200}


# ── Dispatch table ───────────────────────────────────────────────────

ACTION_HANDLERS = {
    'sendMessage': handle_send_message,
    'listChatSessions': handle_list_sessions,
    'createChatSession': handle_create_session,
    'deleteChatSession': handle_delete_session,
    'loadChatHistory': handle_load_history,
}


def lambda_handler(event, context):
    """Handle WebSocket messages — dispatches to action-specific handlers.

    Resolves the calling user's identity from the connections table (written
    at $connect time) and passes it to each action handler for ownership
    enforcement.

    Supports sendMessage (streaming chat), plus session CRUD actions
    (listChatSessions, createChatSession, deleteChatSession, loadChatHistory).
    """
    connection_id = event['requestContext']['connectionId']
    domain_name = event['requestContext']['domainName']
    stage = event['requestContext']['stage']
    endpoint_url = f"https://{domain_name}/{stage}"

    # Resolve user identity once per invocation — all action handlers use it.
    user_sub = _get_user_sub_for_connection(connection_id)
    if not user_sub:
        logger.warning(
            f"No user_sub resolved for connection {connection_id} — "
            "all project access checks will deny"
        )

    try:
        body = json.loads(event.get('body', '{}'))
        action = body.get('action')

        logger.info(f"Received action: {action} from connection {connection_id}")

        handler = ACTION_HANDLERS.get(action)
        if not handler:
            send_to_connection(connection_id, endpoint_url, {
                'type': 'error',
                'error': f'Unknown action: {action}',
            })
            return {'statusCode': 400}

        return handler(body, connection_id, endpoint_url, user_sub)

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)

        try:
            send_to_connection(connection_id, endpoint_url, {
                'type': 'error',
                'error': 'Internal error processing message',
            })
        except Exception:
            pass

        return {'statusCode': 500}
