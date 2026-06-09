output "dashboard_name" {
  description = "CloudWatch dashboard name"
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}

output "lambda_error_alarm_arn" {
  description = "Lambda error alarm ARN"
  value       = aws_cloudwatch_metric_alarm.lambda_errors.arn
}

output "api_5xx_alarm_arn" {
  description = "API Gateway 5xx error alarm ARN"
  value       = aws_cloudwatch_metric_alarm.api_5xx_errors.arn
}
