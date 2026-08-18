variable "standards_kb_id" {
  description = "Bedrock Knowledge Base ID for the Standards KB (created via deploy script, read from SSM)"
  type        = string
}

variable "standards_ds_id" {
  description = "Bedrock KB data source ID for the Standards KB (created via deploy script, read from SSM)"
  type        = string
}

variable "project_name" {
  description = "Project name prefix for resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, demo)"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days for the Standards KB ingestion (APPLICATION_LOGS) delivery"
  type        = number
  default     = 90
}
