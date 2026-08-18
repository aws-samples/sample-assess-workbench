variable "aws_region" {
  description = "AWS region for resources"
  type        = string
}

variable "aws_account_id" {
  description = <<-EOT
    Expected AWS account ID for this environment. When non-empty, both aws
    providers set allowed_account_ids to [this], so Terraform fails provider
    init if the live credentials resolve to a different account — a declarative
    backstop independent of how the environment was selected. Fed from
    TF_VAR_aws_account_id, which scripts/utils/with-env.sh exports from
    AWS_ACCOUNT_ID. Empty (the default) disables the guard, preserving the
    zero-ceremony single-account path.
  EOT
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment name (e.g. dev, demo, staging, prod)"
  type        = string
}

variable "project_name" {
  description = "Project name for resource naming"
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

  validation {
    condition     = var.lambda_timeout >= 30 && var.lambda_timeout <= 900
    error_message = "Lambda timeout must be between 30 and 900 seconds."
  }
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 512

  validation {
    condition     = var.lambda_memory_size >= 128 && var.lambda_memory_size <= 10240
    error_message = "Lambda memory must be between 128 and 10240 MB."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  # Default to 1 year to satisfy the security baseline (CKV_AWS_338) that
  # scanners evaluate against module defaults. Real deployments override this
  # to a cheaper value in their named tfvars (dev=7, demo=14); those files are
  # not auto-loaded by static analysis, so the default is what gets scanned.
  default = 365

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653], var.log_retention_days)
    error_message = "Log retention must be a valid CloudWatch retention period."
  }
}

variable "enable_api_gateway_logging" {
  description = "Enable API Gateway access logging"
  type        = bool
  default     = true
}

variable "enable_xray_tracing" {
  description = "Enable X-Ray tracing for Lambda and API Gateway"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery for DynamoDB"
  type        = bool
  default     = true
}

variable "dynamodb_kms_key_arn" {
  description = "KMS key ARN for DynamoDB encryption (optional, uses AWS managed key if not provided)"
  type        = string
  default     = ""
}

variable "log_level" {
  description = "Log level for Lambda functions (DEBUG, INFO, WARNING, ERROR)"
  type        = string

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "Log level must be DEBUG, INFO, WARNING, or ERROR."
  }
}

# Cognito configuration
variable "cognito_callback_urls" {
  description = "Allowed callback URLs for Cognito OAuth (frontend URLs)"
  type        = list(string)
  default     = ["http://localhost:8080/callback.html"]
}

variable "cognito_logout_urls" {
  description = "Allowed logout URLs for Cognito"
  type        = list(string)
  default     = ["http://localhost:8080"]
}

variable "manage_api_gateway_account" {
  description = "Whether to create the account-level API Gateway CloudWatch role. Set to false if another stack already manages this."
  type        = bool
  default     = false
}

variable "planner_model_id" {
  description = "Bedrock model ID for the AI review planner"
  type        = string
}

variable "image_analysis_model_id" {
  description = "Bedrock model ID for image analysis (triage + deep analysis)"
  type        = string
}

variable "judge_model_id" {
  description = "Bedrock model ID for the quality judge evaluator"
  type        = string
}

variable "allowed_origins" {
  description = "Allowed CORS origins for API Gateway and S3 (restrict in production)"
  type        = list(string)
  default     = ["*"]
}

variable "deploy_frontend" {
  description = "Deploy the frontend hosting infrastructure (S3 + CloudFront + WAF). Enabled by the shipped tfvars; set to false to skip the edge layer and run the SPA locally via the Vite dev server (task dev)."
  type        = bool
  default     = false
}

variable "enable_api_proxy" {
  description = "Route API and WebSocket traffic through CloudFront for unified, same-origin ingress with WAF, instead of calling API Gateway directly. Requires deploy_frontend = true. Enabled by the shipped tfvars."
  type        = bool
  default     = false
}

variable "cloudfront_url" {
  description = "CloudFront distribution URL (e.g. https://d1234abcd.cloudfront.net). Set after first deploy with deploy_frontend=true. Used for Cognito callback URLs and CORS origins. Empty string means no CloudFront."
  type        = string
  default     = ""
}

# Optional OIDC federation configuration (disabled by default).

variable "federated_login_enabled" {
  description = "Enable optional OIDC federation. When false (default), only the native Cognito user pool is used."
  type        = bool
  default     = false
}

variable "federated_identity_provider" {
  description = "Cognito identity provider name for the OIDC provider."
  type        = string
  default     = ""
}

variable "federated_client_id" {
  description = "OIDC client ID registered with the external identity provider."
  type        = string
  default     = ""
}

variable "federated_issuer" {
  description = "OIDC issuer URL for the external identity provider."
  type        = string
  default     = ""
}

variable "federated_client_secret" {
  description = "OIDC client secret. Sensitive; injected at deploy time (never committed). Empty (default) leaves the identity provider uncreated."
  type        = string
  default     = ""
  sensitive   = true
}
