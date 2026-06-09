# Lambda execution role
resource "aws_iam_role" "lambda_execution" {
  name = "${var.project_name}-api-lambda-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-lambda-role"
    Environment = var.environment
  }
}

# Lambda basic execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# X-Ray tracing policy (if enabled)
resource "aws_iam_role_policy_attachment" "lambda_xray" {
  count      = var.enable_xray_tracing ? 1 : 0
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# S3 read policy - FIXED: specific bucket only (security improvement)
resource "aws_iam_role_policy" "s3_read" {
  name = "s3-read-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadDesignDocuments"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = "${var.design_docs_bucket_arn}/*"
      },
      {
        Sid      = "ListBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = var.design_docs_bucket_arn
      }
    ]
  })
}

# S3 delete policy for project cleanup
resource "aws_iam_role_policy" "s3_delete" {
  name = "s3-delete-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DeleteProjectDocuments"
        Effect = "Allow"
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjects"
        ]
        Resource = "${var.design_docs_bucket_arn}/*"
      }
    ]
  })
}

# DynamoDB access policy
resource "aws_iam_role_policy" "dynamodb_access" {
  name = "dynamodb-access-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DynamoDBReadWrite"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem"
        ]
        Resource = [
          var.dynamodb_table_arn,
          "${var.dynamodb_table_arn}/index/*"
        ]
      }
    ]
  })
}

# S3 write policy for pre-signed URLs
resource "aws_iam_role_policy" "s3_write" {
  name = "s3-write-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "GeneratePresignedUrls"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl"
        ]
        Resource = "${var.design_docs_bucket_arn}/*"
      }
    ]
  })
}

# Step Functions execution policy
resource "aws_iam_role_policy" "step_functions_start" {
  name = "step-functions-start-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StartStepFunctionsExecution"
        Effect = "Allow"
        Action = [
          "states:StartExecution",
          "states:DescribeExecution"
        ]
        Resource = var.step_functions_arn
      },
      {
        Sid    = "ApprovePlanCallback"
        Effect = "Allow"
        Action = [
          "states:SendTaskSuccess",
          "states:SendTaskFailure"
        ]
        Resource = var.step_functions_arn
      }
    ]
  })
}

# WebSocket connections table scan - for looking up connection ID by user sub
resource "aws_iam_role_policy" "connections_scan" {
  count = var.connections_table_name != "" ? 1 : 0
  name  = "connections-scan-policy"
  role  = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ScanConnectionsTable"
        Effect   = "Allow"
        Action   = ["dynamodb:Scan"]
        Resource = "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.connections_table_name}"
      }
    ]
  })
}

# Benchmark runner Lambda invoke policy
resource "aws_iam_role_policy" "benchmark_runner_invoke" {
  name = "benchmark-runner-invoke-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeBenchmarkRunner"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.project_name}-run-benchmark-${var.environment}"
      }
    ]
  })
}

# Bedrock model listing for benchmark model selector
resource "aws_iam_role_policy" "bedrock_list_models" {
  name = "bedrock-list-models-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListFoundationModels"
        Effect   = "Allow"
        Action   = ["bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles"]
        Resource = "*"
      }
    ]
  })
}

# AgentCore Memory cleanup for project deletion
resource "aws_iam_role_policy" "agentcore_memory_cleanup" {
  count = var.shared_memory_arn != "" ? 1 : 0
  name  = "agentcore-memory-cleanup-policy"
  role  = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CleanupMemoryRecords"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:ListMemoryRecords",
          "bedrock-agentcore:BatchDeleteMemoryRecords"
        ]
        Resource = var.shared_memory_arn
      }
    ]
  })
}

# Document KB cleanup for project deletion
resource "aws_iam_role_policy" "document_kb_cleanup" {
  count = var.document_kb_id != "" ? 1 : 0
  name  = "document-kb-cleanup-policy"
  role  = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CleanupKBDocuments"
        Effect = "Allow"
        Action = [
          "bedrock:ListKnowledgeBaseDocuments",
          "bedrock:DeleteKnowledgeBaseDocuments"
        ]
        Resource = "arn:aws:bedrock:*:*:knowledge-base/*"
      }
    ]
  })
}

# Standards corpus S3 access (list, get, put, delete)
resource "aws_iam_role_policy" "standards_s3_read" {
  count = var.standards_bucket_name != "" ? 1 : 0
  name  = "standards-s3-read-policy"
  role  = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadStandardsDocuments"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = "arn:aws:s3:::${var.standards_bucket_name}/*"
      },
      {
        Sid      = "ListStandardsBucket"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = "arn:aws:s3:::${var.standards_bucket_name}"
      },
      {
        Sid    = "WriteStandardsDocuments"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:DeleteObjects"
        ]
        Resource = "arn:aws:s3:::${var.standards_bucket_name}/*"
      }
    ]
  })
}

# Standards KB ingestion operations (start, get, list ingestion jobs)
resource "aws_iam_role_policy" "standards_kb_management" {
  count = var.standards_kb_id != "" ? 1 : 0
  name  = "standards-kb-management-policy"
  role  = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StandardsKBIngestion"
        Effect = "Allow"
        Action = [
          "bedrock:StartIngestionJob",
          "bedrock:GetIngestionJob",
          "bedrock:ListIngestionJobs"
        ]
        Resource = "arn:aws:bedrock:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:knowledge-base/${var.standards_kb_id}"
      }
    ]
  })
}

# Guardrail events table read access (admin endpoint)
resource "aws_iam_role_policy" "guardrail_events_read" {
  name = "guardrail-events-read-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadGuardrailEvents"
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          var.guardrail_events_table_arn,
          "${var.guardrail_events_table_arn}/index/*"
        ]
      }
    ]
  })
}
