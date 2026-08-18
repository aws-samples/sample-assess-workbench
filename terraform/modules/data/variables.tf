variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery for DynamoDB"
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "KMS key ARN for DynamoDB encryption (optional, uses AWS managed key if not provided)"
  type        = string
  default     = ""
}
