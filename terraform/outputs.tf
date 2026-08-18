output "bucket_name" {
  description = "S3 bucket name for design documents"
  value       = module.storage.bucket_name
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = module.storage.bucket_arn
}

output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = module.api.api_endpoint
}

output "health_endpoint" {
  description = "Health check endpoint URL"
  value       = module.api.health_endpoint
}

output "projects_endpoint" {
  description = "Projects endpoint URL"
  value       = module.api.projects_endpoint
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = module.api.lambda_function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = module.api.lambda_function_arn
}

output "api_id" {
  description = "API Gateway REST API ID"
  value       = module.api.api_id
}

output "lambda_log_group" {
  description = "Lambda CloudWatch log group name"
  value       = module.api.lambda_log_group
}

output "api_gateway_log_group" {
  description = "API Gateway CloudWatch log group name"
  value       = module.api.api_gateway_log_group
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for projects"
  value       = module.data.table_name
}

output "dynamodb_table_arn" {
  description = "DynamoDB table ARN"
  value       = module.data.table_arn
}

output "step_functions_state_machine_arn" {
  description = "Step Functions state machine ARN for review workflow"
  value       = module.workflow.state_machine_arn
}

output "step_functions_state_machine_name" {
  description = "Step Functions state machine name"
  value       = module.workflow.state_machine_name
}

output "plan_review_function_name" {
  description = "Plan review Lambda function name"
  value       = module.workflow.plan_review_function_name
}

# WebSocket outputs
output "websocket_url" {
  description = "WebSocket API URL for real-time chat"
  value       = module.websocket.websocket_url
}

output "websocket_api_id" {
  description = "WebSocket API ID"
  value       = module.websocket.websocket_api_id
}

output "websocket_connections_table" {
  description = "WebSocket connections DynamoDB table name"
  value       = module.websocket.connections_table_name
}

# Memory outputs
output "shared_memory_arn" {
  description = "Shared memory resource ARN for all agents"
  value       = module.memory.memory_arn
  sensitive   = true
}

# Auth outputs
output "cognito_user_pool_id" {
  description = "Cognito User Pool ID"
  value       = module.auth.user_pool_id
}

output "cognito_client_id" {
  description = "Cognito App Client ID"
  value       = module.auth.client_id
}

output "cognito_hosted_ui_url" {
  description = "Cognito Hosted UI login URL"
  value       = module.auth.hosted_ui_url
}

output "cognito_issuer_url" {
  description = "Cognito JWT issuer URL"
  value       = module.auth.issuer_url
}

# Edge module outputs (frontend hosting)

output "frontend_url" {
  description = "CloudFront frontend URL (empty when deploy_frontend is false)"
  value       = var.deploy_frontend ? module.edge[0].frontend_url : ""
}

output "edge_bucket_name" {
  description = "S3 bucket for frontend assets (empty when deploy_frontend is false)"
  value       = var.deploy_frontend ? module.edge[0].bucket_name : ""
}

output "edge_distribution_id" {
  description = "CloudFront distribution ID (empty when deploy_frontend is false)"
  value       = var.deploy_frontend ? module.edge[0].cloudfront_distribution_id : ""
}

output "origin_verify_secret" {
  description = "Origin lockdown secret for Vite dev proxy (empty when API proxy is disabled)"
  value       = local.origin_verify_secret
  sensitive   = true
}
