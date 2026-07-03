# WebSocket API Gateway for real-time chat
# Eliminates 30-second HTTP timeout limitation

# WebSocket API
resource "aws_apigatewayv2_api" "websocket" {
  name                       = "${var.project_name}-chat-ws-${var.environment}"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
  description                = "WebSocket API for real-time chat - ${var.environment}"

  tags = {
    Name        = "${var.project_name}-websocket-${var.environment}"
    Environment = var.environment
  }
}

# WebSocket stage with auto-deploy
resource "aws_apigatewayv2_stage" "websocket" {
  api_id      = aws_apigatewayv2_api.websocket.id
  name        = var.environment
  auto_deploy = true

  # Ensure account-level CloudWatch role exists before enabling logging
  depends_on = [aws_api_gateway_account.main]

  default_route_settings {
    throttling_burst_limit = 5000
    throttling_rate_limit  = 10000
  }

  # Access logs (requires CloudWatch Logs role in API Gateway account settings)
  # To enable: set enable_api_gateway_logging = true after configuring the account role
  dynamic "access_log_settings" {
    for_each = var.enable_api_gateway_logging ? [1] : []
    content {
      destination_arn = aws_cloudwatch_log_group.websocket.arn
      format = jsonencode({
        requestId        = "$context.requestId"
        connectionId     = "$context.connectionId"
        eventType        = "$context.eventType"
        routeKey         = "$context.routeKey"
        status           = "$context.status"
        requestTime      = "$context.requestTime"
        integrationError = "$context.integrationErrorMessage"
      })
    }
  }

  tags = {
    Name        = "${var.project_name}-websocket-${var.environment}"
    Environment = var.environment
  }
}

# CloudWatch log group for WebSocket API
resource "aws_cloudwatch_log_group" "websocket" {
  name              = "/aws/apigateway/${var.project_name}-websocket-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-websocket-logs"
    Environment = var.environment
  }
}

# DynamoDB table for WebSocket connections
resource "aws_dynamodb_table" "connections" {
  name         = "${var.project_name}-ws-connections-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  # Point-in-time recovery — negligible cost on this tiny PAY_PER_REQUEST
  # table, and enabling it clears the security baseline (CKV_AWS_28) without
  # a per-finding attestation. The table is ephemeral (TTL-cleaned), so this
  # is belt-and-suspenders rather than a recovery requirement.
  point_in_time_recovery {
    enabled = true
  }

  # TTL for automatic cleanup of stale connections
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.project_name}-ws-connections-${var.environment}"
    Environment = var.environment
    Purpose     = "WebSocket connection management"
  }
}

# Lambda functions for WebSocket handlers
locals {
  lambda_runtime = "python3.13"
  lambda_timeout = 300
  lambda_memory  = 512
}

# Connect handler Lambda
resource "aws_lambda_function" "connect" {
  filename                       = data.archive_file.websocket_handlers.output_path
  function_name                  = "${var.project_name}-ws-connect-${var.environment}"
  role                           = aws_iam_role.websocket_lambda.arn
  handler                        = "websocket_handlers.connect.lambda_handler"
  source_code_hash               = data.archive_file.websocket_handlers.output_base64sha256
  runtime                        = local.lambda_runtime
  timeout                        = 30
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 50

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.connections.name
      ENVIRONMENT       = var.environment
      LOG_LEVEL         = var.environment == "prod" ? "INFO" : "DEBUG"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = "${var.project_name}-ws-connect-${var.environment}"
    Environment = var.environment
  }
}

# Disconnect handler Lambda
resource "aws_lambda_function" "disconnect" {
  filename                       = data.archive_file.websocket_handlers.output_path
  function_name                  = "${var.project_name}-ws-disconnect-${var.environment}"
  role                           = aws_iam_role.websocket_lambda.arn
  handler                        = "websocket_handlers.disconnect.lambda_handler"
  source_code_hash               = data.archive_file.websocket_handlers.output_base64sha256
  runtime                        = local.lambda_runtime
  timeout                        = 30
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 50

  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.connections.name
      ENVIRONMENT       = var.environment
      LOG_LEVEL         = var.environment == "prod" ? "INFO" : "DEBUG"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = "${var.project_name}-ws-disconnect-${var.environment}"
    Environment = var.environment
  }
}

# Message handler Lambda
resource "aws_lambda_function" "message" {
  filename                       = data.archive_file.websocket_handlers.output_path
  function_name                  = "${var.project_name}-ws-message-${var.environment}"
  role                           = aws_iam_role.websocket_lambda.arn
  handler                        = "websocket_handlers.message.lambda_handler"
  source_code_hash               = data.archive_file.websocket_handlers.output_base64sha256
  runtime                        = local.lambda_runtime
  timeout                        = local.lambda_timeout
  memory_size                    = local.lambda_memory
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 20

  environment {
    variables = {
      CONNECTIONS_TABLE      = aws_dynamodb_table.connections.name
      PROJECTS_TABLE         = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = "https://${aws_apigatewayv2_api.websocket.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.environment}"
      PROJECT_NAME           = var.project_name
      SHARED_MEMORY_ARN      = var.shared_memory_arn
      DOCUMENT_KB_ID         = var.document_kb_id
      STANDARDS_KB_ID        = var.standards_kb_id
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.environment == "prod" ? "INFO" : "DEBUG"
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = "${var.project_name}-ws-message-${var.environment}"
    Environment = var.environment
  }
}

# Package WebSocket handlers
data "archive_file" "websocket_handlers" {
  type        = "zip"
  source_dir  = "${path.root}/../api"
  output_path = "${path.root}/.terraform/websocket-handlers-${var.environment}.zip"

  excludes = [
    "core",
    "workflow",
    "rest_api",
    "openapi.yaml",
    "__pycache__",
    "*.pyc"
  ]
}

# CloudWatch log groups for Lambda functions
resource "aws_cloudwatch_log_group" "connect" {
  name              = "/aws/lambda/${aws_lambda_function.connect.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "disconnect" {
  name              = "/aws/lambda/${aws_lambda_function.disconnect.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "message" {
  name              = "/aws/lambda/${aws_lambda_function.message.function_name}"
  retention_in_days = var.log_retention_days
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# WebSocket authorizer Lambda
resource "aws_lambda_function" "authorizer" {
  filename                       = data.archive_file.websocket_handlers.output_path
  function_name                  = "${var.project_name}-ws-authorizer-${var.environment}"
  role                           = aws_iam_role.websocket_lambda.arn
  handler                        = "websocket_handlers.authorizer.lambda_handler"
  source_code_hash               = data.archive_file.websocket_handlers.output_base64sha256
  runtime                        = local.lambda_runtime
  timeout                        = 10
  memory_size                    = 128
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 50

  environment {
    variables = {
      COGNITO_USER_POOL_ID = var.cognito_user_pool_id
      COGNITO_CLIENT_ID    = var.cognito_client_id
      LOG_LEVEL            = var.environment == "prod" ? "INFO" : "DEBUG"
      ORIGIN_VERIFY_SECRET = var.origin_verify_secret
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = {
    Name        = "${var.project_name}-ws-authorizer-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "authorizer" {
  name              = "/aws/lambda/${aws_lambda_function.authorizer.function_name}"
  retention_in_days = var.log_retention_days
}

# API Gateway authorizer for WebSocket $connect
resource "aws_apigatewayv2_authorizer" "websocket" {
  api_id           = aws_apigatewayv2_api.websocket.id
  authorizer_type  = "REQUEST"
  authorizer_uri   = aws_lambda_function.authorizer.invoke_arn
  identity_sources = ["route.request.querystring.token"]
  name             = "${var.project_name}-ws-auth-${var.environment}"
}

resource "aws_lambda_permission" "authorizer" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.websocket.execution_arn}/*"
}
