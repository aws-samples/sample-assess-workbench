# =============================================================================
# 1. LOAD DOCUMENT LAMBDA (with PyMuPDF for PDF text extraction)
# =============================================================================

# Build the Lambda package with dependencies
resource "null_resource" "build_load_document" {
  triggers = {
    source_hash       = filesha256("${path.module}/../../../api/workflow/load_document.py")
    requirements_hash = filesha256("${path.module}/../../../api/workflow/load_document_requirements.txt")
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../../../scripts/build_load_document.sh"
  }
}

data "archive_file" "load_document" {
  type        = "zip"
  source_dir  = "${path.module}/../../../.build/load_document"
  output_path = "${path.root}/.terraform/load-document-${var.environment}.zip"

  depends_on = [null_resource.build_load_document]
}

resource "aws_lambda_function" "load_document" {
  filename                       = data.archive_file.load_document.output_path
  function_name                  = "${var.project_name}-load-document-${var.environment}"
  role                           = aws_iam_role.load_document.arn
  handler                        = "load_document.lambda_handler"
  source_code_hash               = data.archive_file.load_document.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 180
  memory_size                    = 512
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME     = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT  = var.websocket_api_endpoint
      CONNECTIONS_TABLE       = var.connections_table_name
      IMAGE_ANALYSIS_MODEL_ID = var.image_analysis_model_id
      ENVIRONMENT             = var.environment
      LOG_LEVEL               = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "load_document" {
  name              = "/aws/lambda/${aws_lambda_function.load_document.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "load_document" {
  name               = "${var.project_name}-load-document-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "load_document" {
  name = "lambda-policy"
  role = aws_iam_role.load_document.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:HeadObject", "s3:PutObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = var.dynamodb_table_arn
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["arn:aws:bedrock:*::foundation-model/anthropic.claude-*", "arn:aws:bedrock:*:*:inference-profile/*"]
      },
      local.websocket_statement,
      local.connections_scan_statement,
    ]
  })
}

# =============================================================================
# 1b. INDEX DOCUMENT LAMBDA (pushes document to Bedrock KB for semantic search)
# =============================================================================

data "archive_file" "index_document" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/index_document.py"
  output_path = "${path.root}/.terraform/index-document-${var.environment}.zip"
}

resource "aws_lambda_function" "index_document" {
  filename                       = data.archive_file.index_document.output_path
  function_name                  = "${var.project_name}-index-document-${var.environment}"
  role                           = aws_iam_role.index_document.arn
  handler                        = "index_document.lambda_handler"
  source_code_hash               = data.archive_file.index_document.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 60
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DOCUMENT_KB_ID         = var.document_kb_id
      DOCUMENT_DS_ID         = var.document_ds_id
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "index_document" {
  name              = "/aws/lambda/${aws_lambda_function.index_document.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "index_document" {
  name               = "${var.project_name}-index-document-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "index_document" {
  name = "lambda-policy"
  role = aws_iam_role.index_document.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect = "Allow"
        Action = [
          "bedrock:IngestKnowledgeBaseDocuments",
          "bedrock:GetKnowledgeBaseDocuments",
          "bedrock:ListKnowledgeBaseDocuments",
          "bedrock:DeleteKnowledgeBaseDocuments",
        ]
        Resource = "arn:aws:bedrock:*:*:knowledge-base/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      local.websocket_statement,
      local.connections_scan_statement,
      local.events_write_statement,
    ]
  })
}

# =============================================================================
# 2. PLAN REVIEW LAMBDA
# =============================================================================

data "archive_file" "plan_review" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/plan_review.py"
  output_path = "${path.root}/.terraform/plan-review-${var.environment}.zip"
}

resource "aws_lambda_function" "plan_review" {
  filename                       = data.archive_file.plan_review.output_path
  function_name                  = "${var.project_name}-plan-review-${var.environment}"
  role                           = aws_iam_role.plan_review.arn
  handler                        = "plan_review.lambda_handler"
  source_code_hash               = data.archive_file.plan_review.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 180
  memory_size                    = 512
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      PLANNER_MODEL_ID       = var.planner_model_id
      PROJECTS_TABLE         = var.dynamodb_table_name
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      PROJECT_NAME           = var.project_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "plan_review" {
  name              = "/aws/lambda/${aws_lambda_function.plan_review.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "plan_review" {
  name               = "${var.project_name}-plan-review-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "plan_review" {
  name = "lambda-policy"
  role = aws_iam_role.plan_review.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["arn:aws:bedrock:*::foundation-model/anthropic.claude-*", "arn:aws:bedrock:*:*:inference-profile/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:PutItem"]
        Resource = var.dynamodb_table_arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      local.websocket_statement,
      local.connections_scan_statement,
    ]
  })
}

# =============================================================================
# 2b. NOTIFY AGENT STATUS LAMBDA (sends WebSocket events for timeout/failure)
# =============================================================================

data "archive_file" "notify_agent_status" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/notify_agent_status.py"
  output_path = "${path.root}/.terraform/notify-agent-status-${var.environment}.zip"
}

resource "aws_lambda_function" "notify_agent_status" {
  filename                       = data.archive_file.notify_agent_status.output_path
  function_name                  = "${var.project_name}-notify-agent-status-${var.environment}"
  role                           = aws_iam_role.notify_agent_status.arn
  handler                        = "notify_agent_status.lambda_handler"
  source_code_hash               = data.archive_file.notify_agent_status.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 15
  memory_size                    = 128
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "notify_agent_status" {
  name              = "/aws/lambda/${aws_lambda_function.notify_agent_status.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "notify_agent_status" {
  name               = "${var.project_name}-notify-agent-status-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "notify_agent_status" {
  name = "lambda-policy"
  role = aws_iam_role.notify_agent_status.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      local.websocket_statement,
      local.connections_scan_statement,
      local.events_write_statement,
    ]
  })
}

# =============================================================================
# 3. INVOKE REVIEW AGENT LAMBDA
# =============================================================================

data "archive_file" "invoke_review_agent" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/invoke_review_agent.py"
  output_path = "${path.root}/.terraform/invoke-review-agent-${var.environment}.zip"
}

resource "aws_lambda_function" "invoke_review_agent" {
  filename                       = data.archive_file.invoke_review_agent.output_path
  function_name                  = "${var.project_name}-invoke-review-agent-${var.environment}"
  role                           = aws_iam_role.invoke_review_agent.arn
  handler                        = "invoke_review_agent.lambda_handler"
  source_code_hash               = data.archive_file.invoke_review_agent.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 600
  memory_size                    = 512
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      SHARED_MEMORY_ARN      = var.shared_memory_arn
      DOCUMENT_KB_ID         = var.document_kb_id
      STANDARDS_KB_ID        = var.standards_kb_id
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "invoke_review_agent" {
  name              = "/aws/lambda/${aws_lambda_function.invoke_review_agent.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "invoke_review_agent" {
  name               = "${var.project_name}-invoke-review-agent-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "invoke_review_agent" {
  name = "lambda-policy"
  role = aws_iam_role.invoke_review_agent.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect = "Allow"
        Action = ["bedrock-agentcore:InvokeAgentRuntime"]
        Resource = [
          "arn:aws:bedrock-agentcore:*:*:runtime/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:BatchCreateMemoryRecords"]
        Resource = var.shared_memory_arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      local.websocket_statement,
      local.connections_scan_statement,
      local.events_write_statement,
    ]
  })
}

# =============================================================================
# 4. AGGREGATE RESULTS LAMBDA
# =============================================================================

data "archive_file" "aggregate_results" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/aggregate_results.py"
  output_path = "${path.root}/.terraform/aggregate-results-${var.environment}.zip"
}

resource "aws_lambda_function" "aggregate_results" {
  filename                       = data.archive_file.aggregate_results.output_path
  function_name                  = "${var.project_name}-aggregate-results-${var.environment}"
  role                           = aws_iam_role.aggregate_results.arn
  handler                        = "aggregate_results.lambda_handler"
  source_code_hash               = data.archive_file.aggregate_results.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 60
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      SHARED_MEMORY_ARN      = var.shared_memory_arn
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "aggregate_results" {
  name              = "/aws/lambda/${aws_lambda_function.aggregate_results.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "aggregate_results" {
  name               = "${var.project_name}-aggregate-results-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "aggregate_results" {
  name = "lambda-policy"
  role = aws_iam_role.aggregate_results.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:BatchCreateMemoryRecords"]
        Resource = var.shared_memory_arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      local.websocket_statement,
      local.connections_scan_statement,
      local.events_write_statement,
    ]
  })
}

# =============================================================================
# 5. STORE PLAN LAMBDA (for WaitForApproval callback pattern)
# =============================================================================

data "archive_file" "store_plan" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/store_plan.py"
  output_path = "${path.root}/.terraform/store-plan-${var.environment}.zip"
}

resource "aws_lambda_function" "store_plan" {
  filename                       = data.archive_file.store_plan.output_path
  function_name                  = "${var.project_name}-store-plan-${var.environment}"
  role                           = aws_iam_role.store_plan.arn
  handler                        = "store_plan.lambda_handler"
  source_code_hash               = data.archive_file.store_plan.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 30
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "store_plan" {
  name              = "/aws/lambda/${aws_lambda_function.store_plan.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "store_plan" {
  name               = "${var.project_name}-store-plan-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "store_plan" {
  name = "lambda-policy"
  role = aws_iam_role.store_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = var.dynamodb_table_arn
      },
      {
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure"]
        Resource = aws_sfn_state_machine.review_workflow.arn
      },
      local.websocket_statement,
      local.connections_scan_statement,
    ]
  })
}

# =============================================================================
# 6. INVOKE JUDGE LAMBDA (quality evaluation via Bedrock Converse)
# =============================================================================

data "archive_file" "invoke_judge" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/invoke_judge.py"
  output_path = "${path.root}/.terraform/invoke-judge-${var.environment}.zip"
}

resource "aws_lambda_function" "invoke_judge" {
  filename                       = data.archive_file.invoke_judge.output_path
  function_name                  = "${var.project_name}-invoke-judge-${var.environment}"
  role                           = aws_iam_role.invoke_judge.arn
  handler                        = "invoke_judge.lambda_handler"
  source_code_hash               = data.archive_file.invoke_judge.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 120
  memory_size                    = 512
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      JUDGE_MODEL_ID         = var.judge_model_id
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "invoke_judge" {
  name              = "/aws/lambda/${aws_lambda_function.invoke_judge.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "invoke_judge" {
  name               = "${var.project_name}-invoke-judge-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "invoke_judge" {
  name = "lambda-policy"
  role = aws_iam_role.invoke_judge.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = ["arn:aws:bedrock:*::foundation-model/anthropic.claude-*", "arn:aws:bedrock:*:*:inference-profile/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      local.websocket_statement,
      local.connections_scan_statement,
      local.events_write_statement,
    ]
  })
}

resource "aws_iam_role_policy_attachment" "invoke_judge_xray" {
  role       = aws_iam_role.invoke_judge.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# =============================================================================
# 7. MERGE QUALITY LAMBDA (folds judge scores into findings payload)
# =============================================================================

data "archive_file" "merge_quality" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/merge_quality.py"
  output_path = "${path.root}/.terraform/merge-quality-${var.environment}.zip"
}

resource "aws_lambda_function" "merge_quality" {
  filename                       = data.archive_file.merge_quality.output_path
  function_name                  = "${var.project_name}-merge-quality-${var.environment}"
  role                           = aws_iam_role.merge_quality.arn
  handler                        = "merge_quality.lambda_handler"
  source_code_hash               = data.archive_file.merge_quality.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 30
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "merge_quality" {
  name              = "/aws/lambda/${aws_lambda_function.merge_quality.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "merge_quality" {
  name               = "${var.project_name}-merge-quality-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "merge_quality" {
  name = "lambda-policy"
  role = aws_iam_role.merge_quality.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${var.s3_bucket_arn}/*"
      },
      local.websocket_statement,
      local.connections_scan_statement,
      local.events_write_statement,
    ]
  })
}

resource "aws_iam_role_policy_attachment" "merge_quality_xray" {
  role       = aws_iam_role.merge_quality.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# =============================================================================
# 7b. STORE RESULTS LAMBDA (reads findings from S3, writes to DynamoDB)
# =============================================================================

data "archive_file" "store_results" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/store_results.py"
  output_path = "${path.root}/.terraform/store-results-${var.environment}.zip"
}

resource "aws_lambda_function" "store_results" {
  filename                       = data.archive_file.store_results.output_path
  function_name                  = "${var.project_name}-store-results-${var.environment}"
  role                           = aws_iam_role.store_results.arn
  handler                        = "store_results.lambda_handler"
  source_code_hash               = data.archive_file.store_results.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 60
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      DYNAMODB_TABLE_NAME = var.dynamodb_table_name
      ENVIRONMENT         = var.environment
      LOG_LEVEL           = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "store_results" {
  name              = "/aws/lambda/${aws_lambda_function.store_results.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "store_results" {
  name               = "${var.project_name}-store-results-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "store_results" {
  name = "lambda-policy"
  role = aws_iam_role.store_results.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = var.dynamodb_table_arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "store_results_xray" {
  role       = aws_iam_role.store_results.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# =============================================================================
# RESOLVE AGENT ARNS LAMBDA (maps plan agent types to AgentCore ARNs)
# =============================================================================

data "archive_file" "resolve_agent_arns" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/resolve_agent_arns.py"
  output_path = "${path.root}/.terraform/resolve-agent-arns-${var.environment}.zip"
}

resource "aws_lambda_function" "resolve_agent_arns" {
  filename                       = data.archive_file.resolve_agent_arns.output_path
  function_name                  = "${var.project_name}-resolve-agent-arns-${var.environment}"
  role                           = aws_iam_role.resolve_agent_arns.arn
  handler                        = "resolve_agent_arns.lambda_handler"
  source_code_hash               = data.archive_file.resolve_agent_arns.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 30
  memory_size                    = 256
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 10

  environment {
    variables = {
      PROJECTS_TABLE = var.dynamodb_table_name
      PROJECT_NAME   = var.project_name
      ENVIRONMENT    = var.environment
      LOG_LEVEL      = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "resolve_agent_arns" {
  name              = "/aws/lambda/${aws_lambda_function.resolve_agent_arns.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "resolve_agent_arns" {
  name               = "${var.project_name}-resolve-agent-arns-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "resolve_agent_arns" {
  name = "lambda-policy"
  role = aws_iam_role.resolve_agent_arns.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = var.dynamodb_table_arn
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:*:*:parameter/${var.project_name}/${var.environment}/agent/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "resolve_agent_arns_xray" {
  role       = aws_iam_role.resolve_agent_arns.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# =============================================================================
# =============================================================================
# UPDATE STATUS FAILED LAMBDA (robust error handler with truncation + fallback)
# =============================================================================

data "archive_file" "update_status_failed" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/update_status_failed.py"
  output_path = "${path.root}/.terraform/update-status-failed-${var.environment}.zip"
}

resource "aws_lambda_function" "update_status_failed" {
  filename                       = data.archive_file.update_status_failed.output_path
  function_name                  = "${var.project_name}-update-status-failed-${var.environment}"
  role                           = aws_iam_role.update_status_failed.arn
  handler                        = "update_status_failed.lambda_handler"
  source_code_hash               = data.archive_file.update_status_failed.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 30
  memory_size                    = 128
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 5

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "update_status_failed" {
  name              = "/aws/lambda/${aws_lambda_function.update_status_failed.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "update_status_failed" {
  name               = "${var.project_name}-update-status-failed-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "update_status_failed" {
  name = "lambda-policy"
  role = aws_iam_role.update_status_failed.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = var.dynamodb_table_arn
      },
      local.websocket_statement,
      local.connections_scan_statement,
    ]
  })
}

resource "aws_iam_role_policy_attachment" "update_status_failed_xray" {
  role       = aws_iam_role.update_status_failed.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# =============================================================================
# CLEANUP STALE REVIEWS LAMBDA (EventBridge scheduled, every 30 min)
# =============================================================================

data "archive_file" "cleanup_stale_reviews" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/cleanup_stale_reviews.py"
  output_path = "${path.root}/.terraform/cleanup-stale-reviews-${var.environment}.zip"
}

resource "aws_lambda_function" "cleanup_stale_reviews" {
  filename                       = data.archive_file.cleanup_stale_reviews.output_path
  function_name                  = "${var.project_name}-cleanup-stale-reviews-${var.environment}"
  role                           = aws_iam_role.cleanup_stale_reviews.arn
  handler                        = "cleanup_stale_reviews.lambda_handler"
  source_code_hash               = data.archive_file.cleanup_stale_reviews.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 120
  memory_size                    = 128
  reserved_concurrent_executions = 1

  environment {
    variables = {
      DYNAMODB_TABLE_NAME   = var.dynamodb_table_name
      STALE_THRESHOLD_HOURS = "2"
      ENVIRONMENT           = var.environment
      LOG_LEVEL             = var.log_level
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "cleanup_stale_reviews" {
  name              = "/aws/lambda/${aws_lambda_function.cleanup_stale_reviews.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "cleanup_stale_reviews" {
  name               = "${var.project_name}-cleanup-stale-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "cleanup_stale_reviews" {
  name = "lambda-policy"
  role = aws_iam_role.cleanup_stale_reviews.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:UpdateItem"]
        Resource = [var.dynamodb_table_arn, "${var.dynamodb_table_arn}/index/GSI1"]
      },
      {
        Effect   = "Allow"
        Action   = ["states:DescribeExecution"]
        Resource = "arn:aws:states:*:*:execution:${var.project_name}-*"
      },
    ]
  })
}

resource "aws_cloudwatch_event_rule" "cleanup_stale_reviews" {
  name                = "${var.project_name}-cleanup-stale-${var.environment}"
  description         = "Trigger stale review cleanup every 30 minutes"
  schedule_expression = "rate(30 minutes)"
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "cleanup_stale_reviews" {
  rule = aws_cloudwatch_event_rule.cleanup_stale_reviews.name
  arn  = aws_lambda_function.cleanup_stale_reviews.arn
}

resource "aws_lambda_permission" "cleanup_stale_reviews" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup_stale_reviews.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cleanup_stale_reviews.arn
}

# X-RAY TRACING — IAM policy attachments for all workflow Lambdas
# =============================================================================

resource "aws_iam_role_policy_attachment" "load_document_xray" {
  role       = aws_iam_role.load_document.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "plan_review_xray" {
  role       = aws_iam_role.plan_review.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "invoke_review_agent_xray" {
  role       = aws_iam_role.invoke_review_agent.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "aggregate_results_xray" {
  role       = aws_iam_role.aggregate_results.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# =============================================================================
# POST-COMPLETION ERROR HANDLER LAMBDA
# =============================================================================

data "archive_file" "post_completion_error" {
  type        = "zip"
  source_file = "${path.module}/../../../api/workflow/post_completion_error.py"
  output_path = "${path.root}/.terraform/post-completion-error-${var.environment}.zip"
}

resource "aws_lambda_function" "post_completion_error" {
  filename                       = data.archive_file.post_completion_error.output_path
  function_name                  = "${var.project_name}-post-completion-error-${var.environment}"
  role                           = aws_iam_role.post_completion_error.arn
  handler                        = "post_completion_error.lambda_handler"
  source_code_hash               = data.archive_file.post_completion_error.output_base64sha256
  runtime                        = "python3.13"
  timeout                        = 30
  memory_size                    = 128
  layers                         = var.shared_layer_arn
  reserved_concurrent_executions = 5

  environment {
    variables = {
      DYNAMODB_TABLE_NAME    = var.dynamodb_table_name
      WEBSOCKET_API_ENDPOINT = var.websocket_api_endpoint
      CONNECTIONS_TABLE      = var.connections_table_name
      ENVIRONMENT            = var.environment
      LOG_LEVEL              = var.log_level
    }
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "post_completion_error" {
  name              = "/aws/lambda/${aws_lambda_function.post_completion_error.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "post_completion_error" {
  name               = "${var.project_name}-post-completion-error-${var.environment}"
  assume_role_policy = local.lambda_assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role_policy" "post_completion_error" {
  name = "lambda-policy"
  role = aws_iam_role.post_completion_error.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.logs_statement,
      {
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = var.dynamodb_table_arn
      },
      local.websocket_statement,
      local.connections_scan_statement,
    ]
  })
}

resource "aws_iam_role_policy_attachment" "post_completion_error_xray" {
  role       = aws_iam_role.post_completion_error.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "store_plan_xray" {
  role       = aws_iam_role.store_plan.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "notify_agent_status_xray" {
  role       = aws_iam_role.notify_agent_status.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "cleanup_stale_reviews_xray" {
  role       = aws_iam_role.cleanup_stale_reviews.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}
