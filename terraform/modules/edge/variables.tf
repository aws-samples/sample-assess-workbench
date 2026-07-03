variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "aws_region" {
  description = "Region for CSP connect-src scoping (execute-api endpoints live here)"
  type        = string
}

variable "cognito_hosted_ui_url" {
  description = "Cognito hosted UI URL for CSP connect-src (OAuth token exchange)"
  type        = string
}

variable "design_docs_bucket_domain" {
  description = "S3 bucket regional domain for CSP connect-src (pre-signed upload URLs for project files and context documents)"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days for WAF logs"
  type        = number
  default     = 365
}

variable "price_class" {
  description = "CloudFront price class (PriceClass_100, PriceClass_200, PriceClass_All)"
  type        = string
  default     = "PriceClass_100"
}

# ---------- API proxy variables (staging/prod only) ---------------------------

variable "enable_api_proxy" {
  description = "Enable API and WebSocket proxying through CloudFront. When false (default), the distribution serves only the SPA static assets. Set to true in staging/prod tfvars."
  type        = bool
  default     = false
}

variable "api_gateway_endpoint" {
  description = "HTTP API Gateway invoke URL (e.g. https://abc123.execute-api.us-west-2.amazonaws.com/v1). Required when enable_api_proxy is true."
  type        = string
  default     = ""
}

variable "websocket_endpoint" {
  description = "WebSocket API Gateway domain (e.g. pynhbvlqw1.execute-api.us-west-2.amazonaws.com). Required when enable_api_proxy is true."
  type        = string
  default     = ""
}

variable "origin_verify_secret" {
  description = "Shared secret for origin lockdown. CloudFront sends this as X-Origin-Verify header; Lambda validates it. Required when enable_api_proxy is true."
  type        = string
  sensitive   = true
  default     = ""
}
