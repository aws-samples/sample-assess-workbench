# =============================================================================
# 8. BENCHMARK RUNNER LAMBDA (parallel agent + judge for comparative analysis)
# =============================================================================

data "archive_file" "run_benchmark" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/run_benchmark.py"
  output_path = "${path.root}/.terraform/run-benchmark-${var.environment}.zip"
}

resource "aws_lambda_function" "run_benchmark" {
  filename                       = data.archive_file.run_benchmark.output_path
  function_name                  = "${var.project_name}-run-benchmark-${var.environment}"
  role                           = aws_iam_role.run_benchmark.arn
  handler                        = "run_benchmark.lambda_handler"
  source_code_hash               = data.archive_file.run_benchmark.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 900
  memory_size                    = 512
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 5

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = var.dynamodb_table_name
      S3_BUCKET_NAME      = var.s3_bucket_name
      JUDGE_MODEL_ID      = var.judge_model_id
      PROJECT_NAME        = var.project_name
      ENVIRONMENT         = var.environment
      LOG_LEVEL           = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "run_benchmark" {
  name              = "/aws/lambda/${aws_lambda_function.run_benchmark.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "run_benchmark" {
  name               = "${var.project_name}-run-benchmark-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "run_benchmark" {
  name = "lambda-policy"
  role = aws_iam_role.run_benchmark.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:HeadObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = var.dynamodb_table_arn
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:InvokeAgentRuntime"]
        Resource = ["arn:aws:bedrock-agentcore:*:*:runtime/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = ["arn:aws:bedrock:*::foundation-model/*", "arn:aws:bedrock:*:*:inference-profile/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:*:*:parameter/${var.project_name}/${var.environment}/agent/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "run_benchmark_xray" {
  role       = aws_iam_role.run_benchmark.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}
