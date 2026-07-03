variable "project_name" {
  description = "Project name for SSM parameter prefix"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "api_endpoint" {
  description = "HTTP API endpoint URL to write to SSM"
  type        = string
}

variable "websocket_url" {
  description = "WebSocket API URL to write to SSM"
  type        = string
}

variable "cognito_hosted_ui_url" {
  description = "Cognito Hosted UI URL to write to SSM"
  type        = string
}

variable "cognito_client_id" {
  description = "Cognito App Client ID to write to SSM"
  type        = string
}
