"""Chat session and message storage.

Canonical schema for chat sessions and messages in DynamoDB. All chat
writes and reads go through this module to ensure consistent PK/SK
patterns and field names.

Sessions and messages are scoped per user via ``user_sub`` in the sort
key. The ``user_sub`` is resolved server-side from the WebSocket
connection record (never supplied by the client), so a user can only
ever address their own partition: even if they knew another user's
``session_id``, the key built from their own ``user_sub`` would not
match it. This is what prevents cross-user chat visibility on shared
projects.

Session metadata schema:
    PK: PROJECT#{project_id}
    SK: CHATSESSION#{user_sub}#{agent}#{session_id}
    Fields: session_id, agent, title, created_at, updated_at, message_count

Message schema:
    PK: PROJECT#{project_id}
    SK: CHAT#{user_sub}#{agent}#{session_id}#{timestamp}#0_USER  or  #1_AGENT
    Fields: message, role, agent, session_id, timestamp
"""
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid.uuid4())


def _truncate_to_word_boundary(text: str, max_chars: int = 30) -> str:
    """Truncate text to max_chars, trimmed to the last word boundary.

    Args:
        text: Input text to truncate.
        max_chars: Maximum character length.

    Returns:
        Truncated string. If the text is shorter than max_chars, returns
        it unchanged (stripped). If truncation lands mid-word, backs up
        to the previous space.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return truncated[:last_space]
    return truncated


def _session_sk(user_sub: str, agent: str, session_id: str) -> str:
    """Build the sort key for a chat session metadata item.

    Args:
        user_sub: Cognito user sub that owns the session.
        agent: Agent type (e.g. 'security').
        session_id: Session identifier.

    Returns:
        The ``CHATSESSION#{user_sub}#{agent}#{session_id}`` sort key.
    """
    return f'CHATSESSION#{user_sub}#{agent}#{session_id}'


def _session_sk_prefix(user_sub: str, agent: str) -> str:
    """Build the sort-key prefix for listing a user's sessions for an agent.

    Args:
        user_sub: Cognito user sub that owns the sessions.
        agent: Agent type.

    Returns:
        The ``CHATSESSION#{user_sub}#{agent}#`` prefix for ``begins_with``.
    """
    return f'CHATSESSION#{user_sub}#{agent}#'


def _message_sk_prefix(user_sub: str, agent: str, session_id: str) -> str:
    """Build the sort-key prefix for a session's messages.

    Args:
        user_sub: Cognito user sub that owns the messages.
        agent: Agent type.
        session_id: Session identifier.

    Returns:
        The ``CHAT#{user_sub}#{agent}#{session_id}#`` prefix for ``begins_with``.
    """
    return f'CHAT#{user_sub}#{agent}#{session_id}#'


def create_chat_session(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
    title: str = "New conversation",
) -> dict:
    """Create a new chat session and return its metadata.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the session (from the
            WebSocket connection record, never the client).
        agent: Agent type (e.g. 'security').
        title: Initial session title.

    Returns:
        Dict with session_id, agent, title, created_at, updated_at,
        message_count.

    Raises:
        ValueError: If user_sub is empty.
        Exception: Propagates any DynamoDB write errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to create a chat session")

    session_id = _generate_session_id()
    now = datetime.now(tz=timezone.utc).isoformat()

    item = {
        'PK': f'PROJECT#{project_id}',
        'SK': _session_sk(user_sub, agent, session_id),
        'session_id': session_id,
        'agent': agent,
        'title': title,
        'created_at': now,
        'updated_at': now,
        'message_count': 0,
    }
    table.put_item(Item=item)

    return {
        'session_id': session_id,
        'agent': agent,
        'title': title,
        'created_at': now,
        'updated_at': now,
        'message_count': 0,
    }


def list_chat_sessions(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
) -> list[dict]:
    """List a user's sessions for a project+agent, newest-first by created_at.

    Only returns sessions owned by ``user_sub`` — the sort-key prefix is
    scoped to the user, so another user's sessions on the same project are
    physically unreachable by this query.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the sessions.
        agent: Agent type.

    Returns:
        List of session metadata dicts, sorted by created_at ascending
        (oldest first, newest to the right).

    Raises:
        ValueError: If user_sub is empty.
        Exception: Propagates any DynamoDB query errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to list chat sessions")

    sk_prefix = _session_sk_prefix(user_sub, agent)
    response = table.query(
        KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
        ExpressionAttributeValues={
            ':pk': f'PROJECT#{project_id}',
            ':sk': sk_prefix,
        },
        ScanIndexForward=True,
    )
    items = response.get('Items', [])

    # Handle pagination — CHATSESSION items are small but could exceed 1MB
    while 'LastEvaluatedKey' in response:
        response = table.query(
            KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
            ExpressionAttributeValues={
                ':pk': f'PROJECT#{project_id}',
                ':sk': sk_prefix,
            },
            ScanIndexForward=True,
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        items.extend(response.get('Items', []))

    sessions = [
        {
            'session_id': item['session_id'],
            'agent': item['agent'],
            'title': item.get('title', 'New conversation'),
            'created_at': item['created_at'],
            'updated_at': item['updated_at'],
            'message_count': int(item.get('message_count', 0)),
        }
        for item in items
    ]

    # Sort by created_at ascending (oldest first, newest to the right)
    sessions.sort(key=lambda s: s['created_at'])
    return sessions


def delete_chat_session(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
    session_id: str,
) -> int:
    """Delete a user's session and all its messages.

    Deletes the session metadata item and all message items matching
    the session's SK prefix. Uses batch_writer for efficiency. Scoped to
    ``user_sub`` so a user can only delete their own session.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the session.
        agent: Agent type.
        session_id: Session identifier.

    Returns:
        Number of items deleted.

    Raises:
        ValueError: If user_sub is empty.
        Exception: Propagates any DynamoDB errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to delete a chat session")

    pk = f'PROJECT#{project_id}'
    items_to_delete = []

    # Collect session metadata item
    items_to_delete.append({
        'PK': pk,
        'SK': _session_sk(user_sub, agent, session_id),
    })

    # Collect all message items for this session
    msg_prefix = _message_sk_prefix(user_sub, agent, session_id)
    response = table.query(
        KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
        ExpressionAttributeValues={
            ':pk': pk,
            ':sk': msg_prefix,
        },
        ProjectionExpression='#pk, #sk',
        ExpressionAttributeNames={'#pk': 'PK', '#sk': 'SK'},
    )
    for item in response.get('Items', []):
        items_to_delete.append({'PK': item['PK'], 'SK': item['SK']})

    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.query(
            KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
            ExpressionAttributeValues={
                ':pk': pk,
                ':sk': msg_prefix,
            },
            ProjectionExpression='#pk, #sk',
            ExpressionAttributeNames={'#pk': 'PK', '#sk': 'SK'},
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        for item in response.get('Items', []):
            items_to_delete.append({'PK': item['PK'], 'SK': item['SK']})

    with table.batch_writer() as batch:
        for key in items_to_delete:
            batch.delete_item(Key=key)

    return len(items_to_delete)


def store_chat_message(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
    session_id: str,
    user_message: str,
    agent_response: str,
) -> None:
    """Store a user/agent chat turn as two DynamoDB items.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the session.
        agent: Agent type (e.g. 'security').
        session_id: Chat session identifier.
        user_message: The user's message text.
        agent_response: The agent's response text.

    Raises:
        ValueError: If user_sub is empty.
        Exception: Propagates any DynamoDB write errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to store a chat message")

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    sk_prefix = _message_sk_prefix(user_sub, agent, session_id)

    table.put_item(Item={
        'PK': f'PROJECT#{project_id}',
        'SK': f'{sk_prefix}{timestamp}#0_USER',
        'message': user_message,
        'role': 'user',
        'agent': agent,
        'session_id': session_id,
        'timestamp': timestamp,
    })

    table.put_item(Item={
        'PK': f'PROJECT#{project_id}',
        'SK': f'{sk_prefix}{timestamp}#1_AGENT',
        'message': agent_response,
        'role': 'agent',
        'agent': agent,
        'session_id': session_id,
        'timestamp': timestamp,
    })


def update_session_metadata(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
    session_id: str,
    user_message: str,
) -> dict | None:
    """Update session metadata after a message turn.

    Sets updated_at, increments message_count. On first message
    (message_count goes from 0 to 1), sets title from user_message
    (first 30 chars, trimmed to word boundary).

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the session.
        agent: Agent type.
        session_id: Chat session identifier.
        user_message: The user's message (used for title on first turn).

    Returns:
        Dict with ``session_id`` and ``title`` if the title was updated
        (first message), otherwise None.

    Raises:
        ValueError: If user_sub is empty, or if the session doesn't exist.
        Exception: Propagates any DynamoDB update errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to update session metadata")

    now = datetime.now(tz=timezone.utc).isoformat()

    key = {
        'PK': f'PROJECT#{project_id}',
        'SK': _session_sk(user_sub, agent, session_id),
    }
    response = table.get_item(Key=key)
    item = response.get('Item')
    if not item:
        raise ValueError(
            f"Chat session not found: project={project_id}, "
            f"agent={agent}, session={session_id}"
        )

    current_count = int(item.get('message_count', 0))

    update_expr = 'SET updated_at = :now, message_count = :count'
    expr_values: dict = {
        ':now': now,
        ':count': current_count + 1,
    }

    title_updated = None

    # On first message, set title from user message
    if current_count == 0:
        title = _truncate_to_word_boundary(user_message, 30)
        update_expr += ', title = :title'
        expr_values[':title'] = title
        title_updated = {'session_id': session_id, 'title': title}

    table.update_item(
        Key=key,
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )

    return title_updated


def load_chat_history(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
    session_id: str,
    max_turns: int = 10,
) -> str:
    """Load recent chat history for a session, formatted for agent prompt.

    Returns a formatted string of recent turns for injection into the
    agent's prompt context. Scoped to ``user_sub``.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the session.
        agent: Agent type.
        session_id: Chat session identifier.
        max_turns: Maximum number of user/agent turn pairs to return.

    Returns:
        Formatted chat history string, or empty string if no history.

    Raises:
        ValueError: If user_sub is empty.
        Exception: Propagates any DynamoDB query errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to load chat history")

    sk_prefix = _message_sk_prefix(user_sub, agent, session_id)
    response = table.query(
        KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
        ExpressionAttributeValues={
            ':pk': f'PROJECT#{project_id}',
            ':sk': sk_prefix,
        },
        ScanIndexForward=True,
    )
    items = response.get('Items', [])

    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.query(
            KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
            ExpressionAttributeValues={
                ':pk': f'PROJECT#{project_id}',
                ':sk': sk_prefix,
            },
            ScanIndexForward=True,
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        items.extend(response.get('Items', []))

    if not items:
        return ""

    recent = items[-(max_turns * 2):]

    lines = []
    for item in recent:
        role = item.get('role', 'unknown')
        text = item.get('message', '')
        label = 'User' if role == 'user' else 'Agent'
        lines.append(f"{label}: {text}")

    return "\n".join(lines)


def load_chat_messages(
    table,
    project_id: str,
    user_sub: str,
    agent: str,
    session_id: str,
) -> list[dict]:
    """Load all messages for a session, structured for frontend display.

    Distinct from load_chat_history which returns a formatted string
    for the agent prompt. This returns structured dicts for the UI.
    Scoped to ``user_sub``.

    Args:
        table: boto3 DynamoDB Table resource.
        project_id: Project identifier.
        user_sub: Cognito user sub that owns the session.
        agent: Agent type.
        session_id: Chat session identifier.

    Returns:
        List of message dicts with role, content, timestamp keys,
        ordered chronologically.

    Raises:
        ValueError: If user_sub is empty.
        Exception: Propagates any DynamoDB query errors.
    """
    if not user_sub:
        raise ValueError("user_sub is required to load chat messages")

    sk_prefix = _message_sk_prefix(user_sub, agent, session_id)
    response = table.query(
        KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
        ExpressionAttributeValues={
            ':pk': f'PROJECT#{project_id}',
            ':sk': sk_prefix,
        },
        ScanIndexForward=True,
    )
    items = response.get('Items', [])

    # Handle pagination
    while 'LastEvaluatedKey' in response:
        response = table.query(
            KeyConditionExpression='PK = :pk AND begins_with(SK, :sk)',
            ExpressionAttributeValues={
                ':pk': f'PROJECT#{project_id}',
                ':sk': sk_prefix,
            },
            ScanIndexForward=True,
            ExclusiveStartKey=response['LastEvaluatedKey'],
        )
        items.extend(response.get('Items', []))

    return [
        {
            'role': item.get('role', 'unknown'),
            'content': item.get('message', ''),
            'timestamp': item.get('timestamp', ''),
        }
        for item in items
    ]
