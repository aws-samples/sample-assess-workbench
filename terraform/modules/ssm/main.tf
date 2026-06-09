# SSM Parameter Store - reads AgentCore config written by deploy scripts
# and writes Terraform outputs for frontend consumption

locals {
  ssm_prefix = "/${var.project_name}/${var.environment}"
}

# Read shared memory ARN from SSM (written by deploy scripts)
data "aws_ssm_parameter" "shared_memory_arn" {
  name = "${local.ssm_prefix}/memory/shared_memory_arn"
}

# Read Document Index KB IDs from SSM (written by deploy_document_kb.sh)
# These are optional — if the parameters don't exist, Terraform plan will
# fail. Run deploy_document_kb.sh first, or set empty defaults in SSM.
data "aws_ssm_parameter" "document_kb_id" {
  name = "${local.ssm_prefix}/kb/document_kb_id"
}

data "aws_ssm_parameter" "document_ds_id" {
  name = "${local.ssm_prefix}/kb/document_ds_id"
}

# Read Standards KB ID and Data Source ID from SSM (written by deploy_standards_kb.sh)
data "aws_ssm_parameter" "standards_kb_id" {
  name = "${local.ssm_prefix}/kb/standards_kb_id"
}

data "aws_ssm_parameter" "standards_ds_id" {
  name = "${local.ssm_prefix}/kb/standards_ds_id"
}

# Write Terraform outputs to SSM (for frontend and other consumers)
resource "aws_ssm_parameter" "api_endpoint" {
  name        = "${local.ssm_prefix}/infra/api_endpoint"
  type        = "String"
  value       = var.api_endpoint
  description = "HTTP API endpoint URL"
  overwrite   = true
}

resource "aws_ssm_parameter" "websocket_url" {
  name        = "${local.ssm_prefix}/infra/websocket_url"
  type        = "String"
  value       = var.websocket_url
  description = "WebSocket API URL"
  overwrite   = true
}

resource "aws_ssm_parameter" "cognito_hosted_ui_url" {
  name        = "${local.ssm_prefix}/auth/cognito_hosted_ui_url"
  type        = "String"
  value       = var.cognito_hosted_ui_url
  description = "Cognito Hosted UI URL"
  overwrite   = true
}

resource "aws_ssm_parameter" "cognito_client_id" {
  name        = "${local.ssm_prefix}/auth/cognito_client_id"
  type        = "String"
  value       = var.cognito_client_id
  description = "Cognito App Client ID"
  overwrite   = true
}
