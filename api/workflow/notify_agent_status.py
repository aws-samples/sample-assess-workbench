"""
Notify Agent Status Lambda — Sends a WebSocket progress event for agent
status changes that occur in Step Functions states (not in agent code).

Called by RecoverFromError and AgentFailed states to notify the UI
of timeouts and failures in real time, then passes through the result.
"""
import logging
import os

from core.progress import send_progress, set_user_sub, set_review_context

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
# This Lambda has two modes: individual agent status and check_group.
# The union is declared here.
EXPECTED_EVENT = {
    'required': [],
    'optional': ['agent_type', 'findings', 'summary', 'metrics', 'status',
                 'status_reason', 'connection_id', 'user_sub', 'websocket_endpoint',
                 'mode', 'group_results', 'project_id', 'review_id'],
}

WEBSOCKET_API_ENDPOINT = os.environ.get('WEBSOCKET_API_ENDPOINT', '')


def lambda_handler(event: dict, context) -> dict:
    # Mode: check_group — inspect group results for failed agents
    if event.get('mode') == 'check_group':
        set_user_sub(event.get('user_sub', ''))
        set_review_context(event.get('project_id', ''), event.get('review_id', ''))
        return _check_group_results(event, context)

    # Default mode: notify individual agent status
    agent_type = event.get('agent_type', 'unknown')
    status = event.get('status', 'unknown')
    status_reason = event.get('status_reason', '')
    findings = event.get('findings', [])
    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '') or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get('user_sub', ''))
    set_review_context(event.get('project_id', ''), event.get('review_id', ''))

    logger.info(f"Agent {agent_type} status={status}: {status_reason}")

    send_progress(connection_id, websocket_endpoint, f'agent_{status}', {
        'agent': agent_type,
        'status': status,
        'status_reason': status_reason,
        'finding_count': len(findings),
    })

    # Return the result fields for the Map state output
    return {
        'agent_type': agent_type,
        'findings': findings,
        'summary': event.get('summary', ''),
        'metrics': event.get('metrics', {}),
        'status': status,
        'status_reason': status_reason,
    }


def _check_group_results(event: dict, context) -> list:
    """Check a group's agent results for failures.

    If any agent has status 'failed', sends a WebSocket event and raises
    an error to abort the outer Map (skipping remaining groups).
    Returns the results unchanged if all agents succeeded.
    """
    group_results = event['group_results']
    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '') or WEBSOCKET_API_ENDPOINT

    failed_agents = [
        r['agent_type'] for r in group_results
        if r.get('status') == 'failed'
    ]

    if failed_agents:
        logger.warning(f"Group has failed agents: {failed_agents}")
        send_progress(connection_id, websocket_endpoint, 'review_aborted', {
            'reason': 'agent_failure',
            'failed_agents': failed_agents,
            'message': f"Review aborted — {', '.join(failed_agents)} failed. Partial results preserved.",
        })
        raise AgentGroupFailedError(
            f"Aborting review: agents failed: {', '.join(failed_agents)}"
        )

    return group_results


class AgentGroupFailedError(Exception):
    """Raised when one or more agents in a group fail, triggering review abort."""
    pass
