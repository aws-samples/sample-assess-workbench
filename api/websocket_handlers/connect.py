"""WebSocket connection handler."""
import json
import os
import boto3
from datetime import datetime, timedelta, timezone
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# DynamoDB client
dynamodb = boto3.resource('dynamodb')
connections_table = dynamodb.Table(os.environ['CONNECTIONS_TABLE'])


def lambda_handler(event, context):
    """
    Handle new WebSocket connection.
    
    Stores connection ID in DynamoDB with TTL for automatic cleanup.
    """
    connection_id = event['requestContext']['connectionId']
    
    try:
        logger.info(f"New WebSocket connection: {connection_id}")
        
        # Extract user_sub from authorizer context (set by Lambda authorizer)
        authorizer_context = event.get('requestContext', {}).get('authorizer', {})
        user_sub = authorizer_context.get('sub', '')
        
        # Store connection with 2-hour TTL
        ttl = int((datetime.now(tz=timezone.utc) + timedelta(hours=2)).timestamp())
        
        item = {
            'connectionId': connection_id,
            'connectedAt': datetime.now(tz=timezone.utc).isoformat(),
            'ttl': ttl
        }
        if user_sub:
            item['userSub'] = user_sub

        connections_table.put_item(Item=item)
        
        logger.info(f"Connection {connection_id} stored successfully (user: {user_sub})")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Connected'})
        }
    
    except Exception as e:
        logger.error(f"Error handling connection: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to connect'})
        }
