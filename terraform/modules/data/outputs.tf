output "table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.projects.name
}

output "table_arn" {
  description = "DynamoDB table ARN"
  value       = aws_dynamodb_table.projects.arn
}

output "table_stream_arn" {
  description = "DynamoDB table stream ARN (if streams enabled)"
  value       = aws_dynamodb_table.projects.stream_arn
}

output "gsi1_name" {
  description = "Global secondary index name"
  value       = "GSI1"
}

output "guardrail_events_table_name" {
  description = "DynamoDB guardrail events table name"
  value       = aws_dynamodb_table.guardrail_events.name
}

output "guardrail_events_table_arn" {
  description = "DynamoDB guardrail events table ARN"
  value       = aws_dynamodb_table.guardrail_events.arn
}
