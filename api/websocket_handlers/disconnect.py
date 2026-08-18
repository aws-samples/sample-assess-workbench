"""WebSocket disconnection handler."""

import json
import os
import boto3
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# DynamoDB client
dynamodb = boto3.resource("dynamodb")
connections_table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


def lambda_handler(event, context):
    """
    Handle WebSocket disconnection.

    Removes connection ID from DynamoDB.
    """
    connection_id = event["requestContext"]["connectionId"]

    try:
        logger.info(f"WebSocket disconnection: {connection_id}")

        # Remove connection from table
        connections_table.delete_item(Key={"connectionId": connection_id})

        logger.info(f"Connection {connection_id} removed successfully")

        return {"statusCode": 200, "body": json.dumps({"message": "Disconnected"})}

    except Exception as e:
        logger.error(f"Error handling disconnection: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": "Failed to disconnect"})}
