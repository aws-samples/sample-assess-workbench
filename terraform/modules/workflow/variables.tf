# Variables for adaptive workflow module

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "planner_model_id" {
  description = "Bedrock model ID for the review planner"
  type        = string
}

variable "shared_memory_arn" {
  description = "ARN of the shared AgentCore memory resource"
  type        = string
}

variable "document_kb_id" {
  description = "Bedrock Knowledge Base ID for the Document Index"
  type        = string
  default     = ""
}

variable "document_ds_id" {
  description = "Bedrock KB data source ID for the Document Index"
  type        = string
  default     = ""
}

variable "standards_kb_id" {
  description = "Bedrock Knowledge Base ID for the Standards KB"
  type        = string
  default     = ""
}

variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table"
  type        = string
}

variable "dynamodb_table_arn" {
  description = "ARN of the DynamoDB table"
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket for documents"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 365
}

variable "log_level" {
  description = "Log level for Lambda functions"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "connections_table_name" {
  description = "DynamoDB WebSocket connections table name"
  type        = string
  default     = ""
}

variable "connections_table_arn" {
  description = "DynamoDB WebSocket connections table ARN"
  type        = string
  default     = ""
}

variable "websocket_api_endpoint" {
  description = "WebSocket API management endpoint URL for posting progress events"
  type        = string
  default     = ""
}

variable "websocket_api_execution_arn" {
  description = "WebSocket API execution ARN for IAM permissions"
  type        = string
  default     = ""
}

variable "image_analysis_model_id" {
  description = "Bedrock model ID for image analysis (triage + deep analysis)"
  type        = string
}

variable "shared_layer_arn" {
  description = "ARNs of the Lambda layers (dependencies + core)"
  type        = list(string)
}

variable "judge_model_id" {
  description = "Bedrock model ID for the quality judge evaluator"
  type        = string
}
