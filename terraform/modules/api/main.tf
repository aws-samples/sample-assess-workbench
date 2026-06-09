# Lambda function package
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.root}/../api"
  output_path = "${path.root}/.terraform/lambda-${var.environment}.zip"

  excludes = [
    "core",
    "workflow",
    "websocket_handlers",
    "openapi.yaml",
    "__pycache__",
    "*.pyc"
  ]
}

# Lambda function
resource "aws_lambda_function" "api" {
  filename                       = data.archive_file.lambda.output_path
  function_name                  = "${var.project_name}-api-${var.environment}"
  role                           = aws_iam_role.lambda_execution.arn
  handler                        = "rest_api.app.lambda_handler"
  source_code_hash               = data.archive_file.lambda.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = var.lambda_timeout
  memory_size                    = var.lambda_memory_size
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 50

  environment {
    variables = {
      DYNAMODB_TABLE_NAME       = var.dynamodb_table_name
      S3_BUCKET_NAME            = var.design_docs_bucket_name
      STEP_FUNCTIONS_ARN        = var.step_functions_arn
      CONNECTIONS_TABLE         = var.connections_table_name
      WEBSOCKET_API_ENDPOINT    = var.websocket_api_endpoint
      ENVIRONMENT               = var.environment
      LOG_LEVEL                 = var.environment == "prod" ? "INFO" : "DEBUG"
      ALLOWED_ORIGIN            = length(var.allowed_origins) == 1 ? var.allowed_origins[0] : var.allowed_origins[0]
      BENCHMARK_RUNNER_FUNCTION = var.benchmark_runner_function_name
      SHARED_MEMORY_ARN         = var.shared_memory_arn
      DOCUMENT_KB_ID            = var.document_kb_id
      DOCUMENT_DS_ID            = var.document_ds_id
      ORIGIN_VERIFY_SECRET      = var.origin_verify_secret
      STANDARDS_BUCKET_NAME     = var.standards_bucket_name
      STANDARDS_KB_ID           = var.standards_kb_id
      STANDARDS_DS_ID           = var.standards_ds_id
      GUARDRAIL_EVENTS_TABLE    = var.guardrail_events_table_name
      FEDERATION_ENABLED        = tostring(var.federated_login_enabled)
    }
  }

  tracing_config {
    mode = var.enable_xray_tracing ? "Active" : "PassThrough"
  }

  tags = {
    Name        = "${var.project_name}-api-${var.environment}"
    Environment = var.environment
  }

  lifecycle {
    ignore_changes = [
      # Ignore changes to source_code_hash if deploying via CI/CD
      # source_code_hash,
    ]
  }
}

# Lambda log group
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.api.function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-lambda-logs"
    Environment = var.environment
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
