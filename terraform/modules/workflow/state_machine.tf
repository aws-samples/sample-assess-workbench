# =============================================================================
# STEP FUNCTIONS STATE MACHINE — Adaptive Review Workflow
# =============================================================================
#
# The ASL definition lives in statemachine/review_workflow.asl.json.
# This file wires it to Terraform resources via templatefile() and
# defines the IAM role/policy for the state machine.
#
# Flow: InitWorkflow → UpdateStatusInProgress → LoadDocument → PlanReview
#       → WaitForApproval → ResolveAgentARNs → ExecuteGroups (nested Map)
#       → Aggregate → EvaluateQuality → MergeQualityScores → StoreResults
#       → UpdateStatusCompleted
#
# The outer Map iterates over plan.groups sequentially (MaxConcurrency: 1).
# The inner Map iterates over group.agents in parallel (MaxConcurrency: 0).

resource "aws_sfn_state_machine" "review_workflow" {
  name     = "${var.project_name}-review-workflow-${var.environment}"
  role_arn = aws_iam_role.step_functions.arn

  definition = templatefile("${path.module}/statemachine/review_workflow.asl.json", {
    dynamodb_table_name      = var.dynamodb_table_name
    load_document_fn         = aws_lambda_function.load_document.function_name
    index_document_fn        = aws_lambda_function.index_document.function_name
    plan_review_fn           = aws_lambda_function.plan_review.function_name
    store_plan_fn            = aws_lambda_function.store_plan.function_name
    resolve_agent_arns_fn    = aws_lambda_function.resolve_agent_arns.function_name
    invoke_review_agent_fn   = aws_lambda_function.invoke_review_agent.function_name
    invoke_judge_fn          = aws_lambda_function.invoke_judge.function_name
    notify_agent_status_fn   = aws_lambda_function.notify_agent_status.function_name
    aggregate_results_fn     = aws_lambda_function.aggregate_results.function_name
    merge_quality_fn         = aws_lambda_function.merge_quality.function_name
    store_results_fn         = aws_lambda_function.store_results.function_name
    update_status_failed_fn  = aws_lambda_function.update_status_failed.function_name
    post_completion_error_fn = aws_lambda_function.post_completion_error.function_name
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration {
    enabled = true
  }

  tags = var.tags
}

# =============================================================================
# STEP FUNCTIONS IAM
# =============================================================================

resource "aws_cloudwatch_log_group" "step_functions" {
  name              = "/aws/vendedlogs/states/${var.project_name}-review-workflow-${var.environment}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "step_functions" {
  name = "${var.project_name}-step-functions-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "step_functions" {
  name = "step-functions-policy"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction"]
        Resource = [
          aws_lambda_function.load_document.arn,
          aws_lambda_function.index_document.arn,
          aws_lambda_function.plan_review.arn,
          aws_lambda_function.resolve_agent_arns.arn,
          aws_lambda_function.invoke_review_agent.arn,
          aws_lambda_function.aggregate_results.arn,
          aws_lambda_function.store_plan.arn,
          aws_lambda_function.invoke_judge.arn,
          aws_lambda_function.merge_quality.arn,
          aws_lambda_function.store_results.arn,
          aws_lambda_function.notify_agent_status.arn,
          aws_lambda_function.update_status_failed.arn,
          aws_lambda_function.post_completion_error.arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = var.dynamodb_table_arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets"
        ]
        Resource = "*"
      }
    ]
  })
}
