variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "design_docs_bucket_arn" {
  description = "ARN of the S3 bucket containing design documents"
  type        = string
}

variable "design_docs_bucket_name" {
  description = "Name of the S3 bucket containing design documents"
  type        = string
}

variable "api_stage_name" {
  description = "API Gateway stage name"
  type        = string
  default     = "v1"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 512
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 365
}

variable "enable_xray_tracing" {
  description = "Enable X-Ray tracing"
  type        = bool
  default     = true
}

variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table for projects"
  type        = string
}

variable "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table for projects"
  type        = string
}

variable "step_functions_arn" {
  description = "ARN of the Step Functions state machine for review workflow"
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito App Client ID for JWT audience validation"
  type        = string
  default     = ""
}

variable "cognito_issuer_url" {
  description = "Cognito JWT issuer URL"
  type        = string
  default     = ""
}

variable "connections_table_name" {
  description = "DynamoDB WebSocket connections table name"
  type        = string
  default     = ""
}

variable "websocket_api_endpoint" {
  description = "WebSocket API management endpoint for connection lookups"
  type        = string
  default     = ""
}

variable "shared_layer_arn" {
  description = "ARNs of the Lambda layers (dependencies + core)"
  type        = list(string)
}

variable "allowed_origins" {
  description = "Allowed CORS origins for API Gateway"
  type        = list(string)
  default     = ["*"]
}

variable "shared_memory_arn" {
  description = "ARN of the shared AgentCore memory resource for cleanup on project deletion"
  type        = string
  default     = ""
}

variable "document_kb_id" {
  description = "Bedrock Knowledge Base ID for the Document Index (for cleanup on project deletion)"
  type        = string
  default     = ""
}

variable "document_ds_id" {
  description = "Bedrock KB data source ID for the Document Index (for cleanup on project deletion)"
  type        = string
  default     = ""
}

variable "origin_verify_secret" {
  description = "Shared secret for CloudFront origin lockdown. Empty in dev (no verification)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "standards_bucket_name" {
  description = "Name of the S3 bucket containing compliance standards documents"
  type        = string
  default     = ""
}

variable "standards_kb_id" {
  description = "Bedrock Knowledge Base ID for the Standards KB (for ingestion operations)"
  type        = string
  default     = ""
}

variable "standards_ds_id" {
  description = "Bedrock KB data source ID for the Standards KB (for ingestion operations)"
  type        = string
  default     = ""
}

variable "guardrail_events_table_name" {
  description = "Name of the DynamoDB table for guardrail intervention events"
  type        = string
}

variable "guardrail_events_table_arn" {
  description = "ARN of the DynamoDB table for guardrail intervention events"
  type        = string
}

variable "federated_login_enabled" {
  description = "Whether optional OIDC federation is enabled. When true, federated users get read-only API access."
  type        = bool
  default     = false
}
