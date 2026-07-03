# Adaptive workflow for document review processing
# Replaces the monolithic review_processor with 5 specialized Lambdas
# and a nested-Map Step Functions state machine.

locals {
  websocket_manage_arn = var.websocket_api_execution_arn != "" ? "${var.websocket_api_execution_arn}/*" : "arn:aws:execute-api:*:*:*/*/POST/@connections/*"
  connections_table    = var.connections_table_arn != "" ? var.connections_table_arn : "arn:aws:dynamodb:*:*:table/placeholder"

  lambda_assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  # Common CloudWatch Logs statements for all Lambdas
  logs_statement = {
    Effect   = "Allow"
    Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/${var.project_name}-*-${var.environment}:*"
  }

  # Common WebSocket ManageConnections statement
  websocket_statement = {
    Effect   = "Allow"
    Action   = ["execute-api:ManageConnections"]
    Resource = local.websocket_manage_arn
  }

  # Common connections table scan statement (for user_sub → connection lookup)
  connections_scan_statement = {
    Effect   = "Allow"
    Action   = ["dynamodb:Scan"]
    Resource = local.connections_table
  }

  # Common event persistence statement (for send_progress → DynamoDB append)
  events_write_statement = {
    Effect   = "Allow"
    Action   = ["dynamodb:PutItem"]
    Resource = var.dynamodb_table_arn
  }
}
