output "standards_kb_id" {
  description = "Bedrock Knowledge Base ID for the Standards KB"
  value       = var.standards_kb_id
}

output "standards_ds_id" {
  description = "Bedrock KB data source ID for the Standards KB"
  value       = var.standards_ds_id
}

output "application_log_group_name" {
  description = "CloudWatch log group receiving Standards KB ingestion (APPLICATION_LOGS) events"
  value       = aws_cloudwatch_log_group.kb_application.name
}
