# API Gateway HTTP API (v2) with OpenAPI specification
# OpenAPI spec is the source of truth for routes and integrations

locals {
  # Prepare OpenAPI spec with Lambda ARN and Cognito substitution
  openapi_spec = templatefile("${path.root}/../api/openapi.yaml", {
    lambda_invoke_arn  = aws_lambda_function.api.invoke_arn
    cognito_client_id  = var.cognito_client_id
    cognito_issuer_url = var.cognito_issuer_url
  })
}

# HTTP API with OpenAPI body
resource "aws_apigatewayv2_api" "api" {
  name          = "${var.project_name}-api-${var.environment}"
  protocol_type = "HTTP"
  description   = "API for AgentCore Risk Assessor - ${var.environment}"

  body = local.openapi_spec

  # CORS is only exercised in dev (localhost → execute-api directly).
  # In staging/prod, all traffic routes through CloudFront (same-origin) so
  # CORS preflight never fires. Kept for dev workflow compatibility.
  cors_configuration {
    allow_origins = var.allowed_origins
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization", "X-Amz-Date", "X-Api-Key", "X-Amz-Security-Token"]
    max_age       = 300
  }

  tags = {
    Name        = "${var.project_name}-api-${var.environment}"
    Environment = var.environment
  }
}

# API Stage with auto-deploy
resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = var.api_stage_name
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      errorMessage     = "$context.error.message"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    throttling_burst_limit = 5000
    throttling_rate_limit  = 10000
  }

  tags = {
    Name        = "${var.project_name}-api-${var.api_stage_name}"
    Environment = var.environment
  }

  depends_on = [aws_cloudwatch_log_group.api_gateway]
}

# Lambda integration (automatically created by OpenAPI spec)
# But we need to grant API Gateway permission to invoke Lambda
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# CloudWatch log group for API Gateway access logs
resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${var.project_name}-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-api-gateway-logs"
    Environment = var.environment
  }
}
