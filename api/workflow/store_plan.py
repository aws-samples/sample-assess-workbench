"""
Store Plan Lambda — Persists the review plan and task token, notifies frontend.
Invoked by Step Functions WaitForApproval state (callback pattern).

This Lambda does NOT call SendTaskSuccess — that happens when the user
approves via the API (review_service.approve_review_plan).
"""
import logging
import os
import boto3
from datetime import datetime, timezone

from core.progress import send_progress, set_user_sub, set_review_context
from core.dynamodb import convert_floats_to_decimal, store_plan

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# ASL ↔ Lambda contract declaration. Used by test_asl_structure.py to
# verify the Step Functions Payload matches what this handler reads.
EXPECTED_EVENT = {
    'required': ['project_id', 'review_id', 'task_token', 'plan'],
    'optional': ['connection_id', 'user_sub', 'websocket_endpoint'],
}

dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
WEBSOCKET_API_ENDPOINT = os.environ.get('WEBSOCKET_API_ENDPOINT', '')


def lambda_handler(event: dict, context) -> dict:
    project_id = event['project_id']
    review_id = event['review_id']
    task_token = event['task_token']
    plan = event['plan']
    connection_id = event.get('connection_id', '')
    websocket_endpoint = event.get('websocket_endpoint', '') or WEBSOCKET_API_ENDPOINT
    set_user_sub(event.get('user_sub', ''))
    set_review_context(event.get('project_id', ''), event.get('review_id', ''))

    # Store plan + task token in DynamoDB
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    ttl = int(datetime.now(tz=timezone.utc).timestamp()) + 3600  # 1 hour expiry

    # Convert plan to DynamoDB-safe format (Decimal for numbers)
    plan_safe = convert_floats_to_decimal(plan)

    store_plan(table, project_id, review_id, plan_safe, task_token, ttl)

    # Notify frontend
    send_progress(connection_id, websocket_endpoint, 'plan_created', {
        'plan': plan,
        'review_id': review_id,
        'requires_approval': True,
    })

    # This Lambda returns nothing meaningful — Step Functions is waiting
    # for SendTaskSuccess via the task token, not for this Lambda's return value.
    return {'stored': True}
