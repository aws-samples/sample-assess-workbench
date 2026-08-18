variable "project_name" {
  description = "Name of the project"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table for projects"
  type        = string
}

variable "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table for projects"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 365
}

variable "enable_api_gateway_logging" {
  description = "Enable API Gateway access logs (requires CloudWatch Logs role in account settings)"
  type        = bool
  default     = false
}

variable "shared_memory_arn" {
  description = "ARN of the shared AgentCore memory resource"
  type        = string
}

variable "cognito_user_pool_id" {
  description = "Cognito User Pool ID for WebSocket authorization"
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito App Client ID for WebSocket authorization"
  type        = string
}

variable "manage_api_gateway_account" {
  description = "Whether to create the account-level API Gateway CloudWatch role. Set to false if another stack already manages this."
  type        = bool
  default     = false
}

variable "shared_layer_arn" {
  description = "ARNs of the Lambda layers (dependencies + core)"
  type        = list(string)
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket for design documents and context files"
  type        = string
}

variable "document_kb_id" {
  description = "Bedrock Knowledge Base ID for the Document Index"
  type        = string
  default     = ""
}

variable "standards_kb_id" {
  description = "Bedrock Knowledge Base ID for the Standards KB"
  type        = string
  default     = ""
}

variable "origin_verify_secret" {
  description = "Shared secret for CloudFront origin lockdown. Empty in dev (no verification)."
  type        = string
  sensitive   = true
  default     = ""
}
