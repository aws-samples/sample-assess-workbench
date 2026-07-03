output "api_id" {
  description = "API Gateway HTTP API ID"
  value       = aws_apigatewayv2_api.api.id
}

output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = aws_apigatewayv2_stage.api.invoke_url
}

output "api_arn" {
  description = "API Gateway ARN"
  value       = aws_apigatewayv2_api.api.arn
}

output "stage_name" {
  description = "API Gateway stage name"
  value       = aws_apigatewayv2_stage.api.name
}

# Convenience endpoints
output "health_endpoint" {
  description = "Health check endpoint URL"
  value       = "${aws_apigatewayv2_stage.api.invoke_url}/health"
}

output "projects_endpoint" {
  description = "Projects endpoint URL"
  value       = "${aws_apigatewayv2_stage.api.invoke_url}/projects"
}

# Lambda outputs
output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.api.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.api.arn
}

output "lambda_log_group" {
  description = "Lambda CloudWatch log group name"
  value       = aws_cloudwatch_log_group.lambda.name
}

output "api_gateway_log_group" {
  description = "API Gateway CloudWatch log group name"
  value       = aws_cloudwatch_log_group.api_gateway.name
}
