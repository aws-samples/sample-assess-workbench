output "websocket_url" {
  description = "WebSocket API URL"
  value       = "wss://${aws_apigatewayv2_api.websocket.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.environment}"
}

output "websocket_api_id" {
  description = "WebSocket API ID"
  value       = aws_apigatewayv2_api.websocket.id
}

output "connections_table_name" {
  description = "DynamoDB connections table name"
  value       = aws_dynamodb_table.connections.name
}

output "connections_table_arn" {
  description = "DynamoDB connections table ARN"
  value       = aws_dynamodb_table.connections.arn
}

output "websocket_api_endpoint" {
  description = "WebSocket API management endpoint for posting to connections"
  value       = "https://${aws_apigatewayv2_api.websocket.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.environment}"
}

output "websocket_api_execution_arn" {
  description = "WebSocket API execution ARN"
  value       = aws_apigatewayv2_api.websocket.execution_arn
}

output "connect_function_name" {
  description = "Connect Lambda function name"
  value       = aws_lambda_function.connect.function_name
}

output "disconnect_function_name" {
  description = "Disconnect Lambda function name"
  value       = aws_lambda_function.disconnect.function_name
}

output "message_function_name" {
  description = "Message Lambda function name"
  value       = aws_lambda_function.message.function_name
}
