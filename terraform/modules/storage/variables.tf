variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 365
}

variable "allowed_origins" {
  description = "Allowed CORS origins for S3 pre-signed URL uploads"
  type        = list(string)
  default     = ["*"]
}
