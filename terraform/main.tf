provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project     = var.project_name
        Environment = var.environment
        ManagedBy   = "Terraform"
      },
      var.tags
    )
  }
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = merge(
      {
        Project     = var.project_name
        Environment = var.environment
        ManagedBy   = "Terraform"
      },
      var.tags
    )
  }
}

# tflint-ignore: terraform_unused_declarations (used by child modules)
data "aws_caller_identity" "current" {}
# tflint-ignore: terraform_unused_declarations (used by child modules)
data "aws_region" "current" {}

# =============================================================================
# Lambda Layers
# =============================================================================

# Layer 1: Dependencies (boto3, python-jose) — changes rarely (~50MB)
resource "null_resource" "build_dependencies_layer" {
  triggers = {
    script_hash = filesha256("${path.module}/../scripts/build_dependencies_layer.sh")
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../scripts/build_dependencies_layer.sh"
  }
}

data "archive_file" "dependencies_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/dependencies_layer"
  output_path = "${path.root}/.terraform/dependencies-layer-${var.environment}.zip"

  depends_on = [null_resource.build_dependencies_layer]
}

resource "aws_lambda_layer_version" "dependencies" {
  filename            = data.archive_file.dependencies_layer.output_path
  layer_name          = "${var.project_name}-dependencies-${var.environment}"
  source_code_hash    = data.archive_file.dependencies_layer.output_base64sha256
  compatible_runtimes = ["python3.13"]
  description         = "Dependencies layer: boto3, python-jose"
}

# Layer 2: Core application code (api/core/) — changes often (~30KB)
resource "null_resource" "build_core_layer" {
  triggers = {
    script_hash = filesha256("${path.module}/../scripts/build_core_layer.sh")
    core_hash   = sha1(join("", [for f in fileset("${path.module}/../api/core", "**/*.py") : filesha256("${path.module}/../api/core/${f}")]))
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../scripts/build_core_layer.sh"
  }
}

data "archive_file" "core_layer" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/core_layer"
  output_path = "${path.root}/.terraform/core-layer-${var.environment}.zip"

  depends_on = [null_resource.build_core_layer]
}

resource "aws_lambda_layer_version" "core" {
  filename            = data.archive_file.core_layer.output_path
  layer_name          = "${var.project_name}-core-${var.environment}"
  source_code_hash    = data.archive_file.core_layer.output_base64sha256
  compatible_runtimes = ["python3.13"]
  description         = "Core layer: shared application code"
}

locals {
  lambda_layer_arns = [
    aws_lambda_layer_version.dependencies.arn,
    aws_lambda_layer_version.core.arn,
  ]

  # Origin lockdown secret — shared between CloudFront (custom origin header)
  # and Lambda (env var validation). Only needed when API proxy is enabled.
  origin_verify_secret = (var.deploy_frontend && var.enable_api_proxy
    ? random_password.origin_verify[0].result : ""
  )

  # Cognito callback/logout URLs and CORS origins that include the CloudFront
  # domain. Sourced from var.cloudfront_url (set in tfvars or by the deploy
  # task after the first apply) rather than from module.edge output. This
  # avoids a dependency cycle: edge → api → auth → edge.
  #
  # The edge module still outputs frontend_url for the deploy task and status
  # display, but Cognito and CORS do not depend on it.
  cloudfront_callback_urls = var.cloudfront_url != "" ? [
    "${var.cloudfront_url}/callback",
    "${var.cloudfront_url}/callback.html",
  ] : []
  cloudfront_logout_urls  = var.cloudfront_url != "" ? [var.cloudfront_url] : []
  cloudfront_cors_origins = var.cloudfront_url != "" ? [var.cloudfront_url] : []

  cognito_callback_urls_composed = concat(var.cognito_callback_urls, local.cloudfront_callback_urls)
  cognito_logout_urls_composed   = concat(var.cognito_logout_urls, local.cloudfront_logout_urls)
  allowed_origins_composed       = concat(var.allowed_origins, local.cloudfront_cors_origins)
}

# SSM module - reads agent ARNs from Parameter Store (written by deploy scripts)
module "ssm" {
  source = "./modules/ssm"

  project_name          = var.project_name
  environment           = var.environment
  api_endpoint          = module.api.api_endpoint
  websocket_url         = module.websocket.websocket_url
  cognito_hosted_ui_url = module.auth.hosted_ui_url
  cognito_client_id     = module.auth.client_id
}

# Auth module - Cognito User Pool for authentication
module "auth" {
  source = "./modules/auth"

  project_name                = var.project_name
  environment                 = var.environment
  callback_urls               = local.cognito_callback_urls_composed
  logout_urls                 = local.cognito_logout_urls_composed
  federated_login_enabled     = var.federated_login_enabled
  federated_identity_provider = var.federated_identity_provider
  federated_client_id         = var.federated_client_id
  federated_issuer            = var.federated_issuer
  federated_provider_ready    = var.federated_provider_ready
}

# Storage module - S3 buckets and policies
module "storage" {
  source = "./modules/storage"

  project_name       = var.project_name
  environment        = var.environment
  log_retention_days = var.log_retention_days
  allowed_origins    = local.allowed_origins_composed
}

# Data module - DynamoDB for projects and chat history
module "data" {
  source = "./modules/data"

  project_name                  = var.project_name
  environment                   = var.environment
  enable_point_in_time_recovery = var.enable_point_in_time_recovery
  kms_key_arn                   = var.dynamodb_kms_key_arn
}

# Memory module - AgentCore Memory for semantic search
module "memory" {
  source = "./modules/memory"

  shared_memory_arn = module.ssm.shared_memory_arn
}

# Document KB module - Bedrock KB for project document indexing
module "document_kb" {
  source = "./modules/document_kb"

  document_kb_id = module.ssm.document_kb_id
  document_ds_id = module.ssm.document_ds_id
}

# Standards KB module - Bedrock KB for compliance standards reference
module "standards_kb" {
  source = "./modules/standards_kb"

  standards_kb_id = module.ssm.standards_kb_id
  standards_ds_id = module.ssm.standards_ds_id
}

# Workflow module - Step Functions for async review processing
module "workflow" {
  source = "./modules/workflow"

  project_name            = var.project_name
  environment             = var.environment
  planner_model_id        = var.planner_model_id
  judge_model_id          = var.judge_model_id
  image_analysis_model_id = var.image_analysis_model_id
  shared_memory_arn       = module.memory.memory_arn
  document_kb_id          = module.document_kb.document_kb_id
  document_ds_id          = module.document_kb.document_ds_id
  standards_kb_id         = module.standards_kb.standards_kb_id
  dynamodb_table_name     = module.data.table_name
  dynamodb_table_arn      = module.data.table_arn
  s3_bucket_arn           = module.storage.bucket_arn
  s3_bucket_name          = module.storage.bucket_name
  log_retention_days      = var.log_retention_days
  log_level               = var.log_level

  connections_table_name      = module.websocket.connections_table_name
  connections_table_arn       = module.websocket.connections_table_arn
  websocket_api_endpoint      = module.websocket.websocket_api_endpoint
  websocket_api_execution_arn = module.websocket.websocket_api_execution_arn
  shared_layer_arn            = local.lambda_layer_arns
}

# API module - API Gateway, Lambda, IAM
module "api" {
  source = "./modules/api"

  project_name                   = var.project_name
  environment                    = var.environment
  design_docs_bucket_arn         = module.storage.bucket_arn
  design_docs_bucket_name        = module.storage.bucket_name
  dynamodb_table_name            = module.data.table_name
  dynamodb_table_arn             = module.data.table_arn
  step_functions_arn             = module.workflow.state_machine_arn
  connections_table_name         = module.websocket.connections_table_name
  websocket_api_endpoint         = module.websocket.websocket_api_endpoint
  api_stage_name                 = var.api_stage_name
  lambda_timeout                 = var.lambda_timeout
  lambda_memory_size             = var.lambda_memory_size
  log_retention_days             = var.log_retention_days
  enable_xray_tracing            = var.enable_xray_tracing
  cognito_client_id              = module.auth.client_id
  cognito_issuer_url             = module.auth.issuer_url
  shared_layer_arn               = local.lambda_layer_arns
  allowed_origins                = local.allowed_origins_composed
  benchmark_runner_function_name = module.workflow.run_benchmark_function_name
  shared_memory_arn              = module.memory.memory_arn
  document_kb_id                 = module.document_kb.document_kb_id
  document_ds_id                 = module.document_kb.document_ds_id
  origin_verify_secret           = local.origin_verify_secret
  standards_bucket_name          = "${var.project_name}-standards-${var.environment}-${data.aws_caller_identity.current.account_id}"
  standards_kb_id                = module.standards_kb.standards_kb_id
  standards_ds_id                = module.standards_kb.standards_ds_id
  guardrail_events_table_name    = module.data.guardrail_events_table_name
  guardrail_events_table_arn     = module.data.guardrail_events_table_arn
  federated_login_enabled        = var.federated_login_enabled
}

# WebSocket module - Real-time chat API
module "websocket" {
  source = "./modules/websocket"

  project_name               = var.project_name
  environment                = var.environment
  dynamodb_table_name        = module.data.table_name
  dynamodb_table_arn         = module.data.table_arn
  shared_memory_arn          = module.memory.memory_arn
  document_kb_id             = module.document_kb.document_kb_id
  standards_kb_id            = module.standards_kb.standards_kb_id
  log_retention_days         = var.log_retention_days
  enable_api_gateway_logging = var.enable_api_gateway_logging
  manage_api_gateway_account = var.manage_api_gateway_account
  cognito_user_pool_id       = module.auth.user_pool_id
  cognito_client_id          = module.auth.client_id
  shared_layer_arn           = local.lambda_layer_arns
  s3_bucket_arn              = module.storage.bucket_arn
  origin_verify_secret       = local.origin_verify_secret
}

# Monitoring module - CloudWatch alarms and dashboards
module "monitoring" {
  source = "./modules/monitoring"

  project_name         = var.project_name
  environment          = var.environment
  lambda_function_name = module.api.lambda_function_name
}

# Guardrails module - Bedrock Guardrail for PII redaction and content filtering
module "guardrails" {
  source = "./modules/guardrails"

  project_name = var.project_name
  environment  = var.environment
}

# Origin lockdown secret for CloudFront → API Gateway origin verification.
# Only needed when the edge module proxies API traffic (staging/prod).
# Lives in the parent (not inside the edge module) because it's a cross-cutting
# concern consumed by both the edge module and the API/WebSocket modules.
resource "random_password" "origin_verify" {
  count   = var.deploy_frontend && var.enable_api_proxy ? 1 : 0
  length  = 32
  special = false # Avoid characters that need URL-encoding in HTTP headers
}

# Edge module - S3 + CloudFront + WAF (optional, for hosted frontend)
module "edge" {
  count  = var.deploy_frontend ? 1 : 0
  source = "./modules/edge"

  project_name          = var.project_name
  environment           = var.environment
  aws_region            = var.aws_region
  cognito_hosted_ui_url = module.auth.hosted_ui_url
  log_retention_days    = var.log_retention_days

  design_docs_bucket_domain = module.storage.bucket_regional_domain_name

  # API proxy (staging/prod): route API + WebSocket through CloudFront.
  # The edge module receives full endpoint URLs and parses the domains itself.
  enable_api_proxy     = var.enable_api_proxy
  api_gateway_endpoint = var.enable_api_proxy ? module.api.api_endpoint : ""
  websocket_endpoint = var.enable_api_proxy ? replace(
    replace(module.websocket.websocket_url, "/^wss?:\\/\\//", ""),
    "/\\/.*$/", ""
  ) : ""
  origin_verify_secret = local.origin_verify_secret

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
}

# Generate frontend configuration from Terraform outputs.
# Written to frontend/public/ so Vite copies it verbatim to dist/ during
# build (public/ files get served at the site root). Vite dev server also
# serves public/ files at the root, so local dev behavior is unchanged.
#
# When API proxy is enabled (staging/prod), use relative URLs through
# CloudFront (same-origin). Otherwise, use direct API Gateway endpoints (dev).
locals {
  api_base_url = (var.deploy_frontend && var.enable_api_proxy
    ? "/api"
    : module.api.api_endpoint
  )
  ws_url = (var.deploy_frontend && var.enable_api_proxy
    ? "wss://${module.edge[0].cloudfront_domain_name}/ws"
    : module.websocket.websocket_url
  )
}

resource "local_file" "frontend_config" {
  content = jsonencode({
    apiBaseUrl           = local.api_base_url
    websocketUrl         = local.ws_url
    cognitoHostedUiUrl   = module.auth.hosted_ui_url
    clientId             = module.auth.client_id
    federationEnabled    = var.federated_login_enabled
    identityProviderName = var.federated_identity_provider
  })
  filename = "${path.root}/../frontend/public/config.json"
}
