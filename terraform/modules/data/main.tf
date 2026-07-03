# DynamoDB table for projects, reviews, and chat history
# Single-table design using PK/SK pattern for flexibility and cost optimization

resource "aws_dynamodb_table" "projects" {
  name         = "${var.project_name}-projects-${var.environment}"
  billing_mode = "PAY_PER_REQUEST" # On-demand pricing for variable workload
  hash_key     = "PK"
  range_key    = "SK"

  # Primary key attributes
  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # GSI for querying by project status and time
  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # GSI2 attributes for per-user project queries
  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  # Global secondary index for status and time-based queries
  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  # Global secondary index for per-user project queries (multi-tenancy)
  # GSI2PK = USER#{user_sub}, GSI2SK = {created_at timestamp}
  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  # Point-in-time recovery for data protection
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  # Server-side encryption
  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }

  # TTL for automatic cleanup of old data (optional)
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.project_name}-projects-${var.environment}"
    Environment = var.environment
    Purpose     = "Project and chat history storage"
  }
}

# CloudWatch alarms for DynamoDB throttling
resource "aws_cloudwatch_metric_alarm" "read_throttle" {
  alarm_name          = "${var.project_name}-dynamodb-read-throttle-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ReadThrottleEvents"
  namespace           = "AWS/DynamoDB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "DynamoDB read throttle events"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.projects.name
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_cloudwatch_metric_alarm" "write_throttle" {
  alarm_name          = "${var.project_name}-dynamodb-write-throttle-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "WriteThrottleEvents"
  namespace           = "AWS/DynamoDB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "DynamoDB write throttle events"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = aws_dynamodb_table.projects.name
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
  }
}

# DynamoDB table for guardrail intervention events (audit log)
# Separate table from projects — different access patterns (time-range scans,
# no relationship to project items) and audit/observability concern.
resource "aws_dynamodb_table" "guardrail_events" {
  name         = "${var.project_name}-guardrail-events-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # Point-in-time recovery — this is an audit log of guardrail interventions,
  # so durability matters. Gated on the same flag as the projects table.
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  # Server-side encryption
  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn != "" ? var.kms_key_arn : null
  }

  # TTL for automatic cleanup of old events (90 days default)
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.project_name}-guardrail-events-${var.environment}"
    Environment = var.environment
    Purpose     = "Guardrail intervention audit log"
  }
}

# SSM parameter to store table name for easy reference
resource "aws_ssm_parameter" "table_name" {
  name        = "/${var.project_name}/${var.environment}/dynamodb-table"
  description = "DynamoDB table name for projects"
  type        = "String"
  value       = aws_dynamodb_table.projects.name

  tags = {
    Environment = var.environment
    Project     = var.project_name
  }
}

resource "aws_ssm_parameter" "guardrail_events_table_name" {
  name        = "/${var.project_name}/${var.environment}/guardrail-events-table"
  description = "DynamoDB table name for guardrail events"
  type        = "String"
  value       = aws_dynamodb_table.guardrail_events.name

  tags = {
    Environment = var.environment
    Project     = var.project_name
  }
}
