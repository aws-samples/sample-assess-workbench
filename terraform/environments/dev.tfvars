# Development environment configuration

environment  = "dev"
aws_region   = "us-west-2"
project_name = "risk-assessor"

# API Gateway configuration
api_stage_name = "v1"

# Frontend hosting (S3 + CloudFront + WAF) and unified API proxy
deploy_frontend  = true
enable_api_proxy = true

# Lambda configuration
lambda_timeout     = 300
lambda_memory_size = 512

# Logging configuration
log_retention_days = 7
log_level          = "INFO"

# Model configuration — these are fallback defaults.
# Preferred: set PLANNER_MODEL_ID and IMAGE_ANALYSIS_MODEL_ID in .env
# (task deploy:infra passes them as -var overrides automatically)
planner_model_id        = "us.anthropic.claude-sonnet-4-6"
image_analysis_model_id = "us.anthropic.claude-sonnet-4-6"

# Feature flags
enable_api_gateway_logging = true
enable_xray_tracing        = true
manage_api_gateway_account = true

# DynamoDB configuration
enable_point_in_time_recovery = true
dynamodb_kms_key_arn          = "" # Use AWS managed key

# Cognito callback URLs (localhost:5173 for Vite dev server added automatically in dev)
cognito_callback_urls = ["http://localhost:8080/callback.html", "http://localhost:8080/callback"]
cognito_logout_urls   = ["http://localhost:8080", "http://localhost:5173"]

# Additional tags
tags = {
  Owner      = "platform-team"
  CostCenter = "engineering"
  Compliance = "required"
}

# NOTE: Agent ARNs and shared memory ARN are read from SSM Parameter Store.
# They are written automatically by the deploy scripts (scripts/deploy_*.sh).
# No need to specify them here.
