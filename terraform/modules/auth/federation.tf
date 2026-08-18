# Optional OIDC federation for Cognito.
#
# Every resource here is gated behind var.federated_login_enabled (default
# false), so a stock deploy creates none of them and authentication uses the
# native Cognito user pool only. To federate with a standard OIDC provider
# (Okta, Entra ID, Google, etc.):
#   1. set federated_login_enabled = true and the federated_* variables,
#   2. provide the OIDC client secret via var.federated_client_secret (injected
#      at deploy time from a local file / TF_VAR — never committed),
#   3. apply once — the provider comes up in a single pass.

# =============================================================================
# Secrets Manager — OIDC client secret
# =============================================================================
# The secret value is supplied by var.federated_client_secret and stored here as
# the system of record (rotation reference). It is also set inline on the Cognito
# identity provider below; either way the value resides in Terraform state, so
# the state backend (KMS-encrypted, access-controlled S3) is the protection.
resource "aws_secretsmanager_secret" "federated_client_secret" {
  count = var.federated_login_enabled ? 1 : 0
  name  = "${var.project_name}-oidc-secret-${var.environment}"

  tags = {
    Name        = "${var.project_name}-oidc-secret-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "federated" {
  count         = var.federated_login_enabled && var.federated_client_secret != "" ? 1 : 0
  secret_id     = aws_secretsmanager_secret.federated_client_secret[0].id
  secret_string = var.federated_client_secret
}

# =============================================================================
# OIDC Identity Provider
# =============================================================================
# Created once the client secret is provided (federated_client_secret non-empty).
resource "aws_cognito_identity_provider" "federated" {
  count         = var.federated_login_enabled && var.federated_client_secret != "" ? 1 : 0
  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = var.federated_identity_provider
  provider_type = "OIDC"

  provider_details = {
    client_id                 = var.federated_client_id
    client_secret             = var.federated_client_secret
    oidc_issuer               = var.federated_issuer
    authorize_scopes          = "openid email"
    attributes_request_method = "GET"
  }

  attribute_mapping = {
    email    = "EMAIL"
    username = "sub"
  }
}

# =============================================================================
# Post-Authentication Lambda
# =============================================================================
# Assigns the default group (viewers) to federated users on first login.
data "archive_file" "post_auth" {
  count       = var.federated_login_enabled ? 1 : 0
  type        = "zip"
  source_file = "${path.module}/../../../api/auth_triggers/post_authentication.py"
  output_path = "${path.module}/../../../.build/post_authentication.zip"
}

resource "aws_lambda_function" "post_auth" {
  count = var.federated_login_enabled ? 1 : 0

  function_name    = "${var.project_name}-post-auth-${var.environment}"
  filename         = data.archive_file.post_auth[0].output_path
  source_code_hash = data.archive_file.post_auth[0].output_base64sha256
  handler          = "post_authentication.handler"
  runtime          = "python3.13"
  timeout          = 10
  memory_size      = 128

  role = aws_iam_role.post_auth[0].arn

  environment {
    variables = {
      # Federated users land here on first login. We assign "viewers", not
      # "admins", on purpose: the posture is default-CLOSED. A viewer has full
      # read visibility but zero write access, so a missing write-gate on some
      # future endpoint fails safe (viewer can't write) rather than open.
      # NOTE: changing this only affects NEW first-login users.
      DEFAULT_GROUP = "viewers"
      LOG_LEVEL     = "INFO"
    }
  }

  tags = {
    Name        = "${var.project_name}-post-auth-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "post_auth" {
  count             = var.federated_login_enabled ? 1 : 0
  name              = "/aws/lambda/${var.project_name}-post-auth-${var.environment}"
  retention_in_days = 14

  tags = {
    Name        = "${var.project_name}-post-auth-${var.environment}"
    Environment = var.environment
  }
}

# IAM role for the Post-Authentication Lambda
resource "aws_iam_role" "post_auth" {
  count = var.federated_login_enabled ? 1 : 0
  name  = "${var.project_name}-post-auth-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name        = "${var.project_name}-post-auth-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "post_auth_cognito" {
  count = var.federated_login_enabled ? 1 : 0
  name  = "CognitoGroupManagement"
  role  = aws_iam_role.post_auth[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cognito-idp:AdminListGroupsForUser",
        "cognito-idp:AdminAddUserToGroup",
      ]
      Resource = aws_cognito_user_pool.main.arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "post_auth_logs" {
  count      = var.federated_login_enabled ? 1 : 0
  role       = aws_iam_role.post_auth[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Allow Cognito to invoke the Lambda
resource "aws_lambda_permission" "post_auth_cognito" {
  count         = var.federated_login_enabled ? 1 : 0
  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.post_auth[0].function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}
