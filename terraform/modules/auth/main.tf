# Cognito User Pool for authentication

resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-users-${var.environment}"

  # Sign-in configuration
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Only admins can create users — no public self-registration
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Password policy
  password_policy {
    minimum_length                   = 8
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  # Account recovery
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Schema attributes
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  # Post-Authentication Lambda trigger (only when OIDC federation is enabled).
  # Assigns the default group to federated users on first login.
  dynamic "lambda_config" {
    for_each = var.federated_login_enabled ? [1] : []
    content {
      post_authentication = aws_lambda_function.post_auth[0].arn
    }
  }

  tags = {
    Name        = "${var.project_name}-users-${var.environment}"
    Environment = var.environment
  }
}

# User Pool Domain for Hosted UI
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${var.environment}-${data.aws_caller_identity.current.account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# App Client for the frontend
resource "aws_cognito_user_pool_client" "frontend" {
  name         = "${var.project_name}-frontend-${var.environment}"
  user_pool_id = aws_cognito_user_pool.main.id

  # OAuth configuration
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = var.federated_login_enabled && var.federated_client_secret != "" ? concat(["COGNITO"], [var.federated_identity_provider]) : ["COGNITO"]

  # Callback URLs
  callback_urls = local.callback_urls
  logout_urls   = local.logout_urls

  # Token configuration
  # When OIDC federation is enabled, use shorter token lifetimes
  # (access 10 min, id 1 hour, refresh 10 hours); otherwise keep permissive
  # defaults for local development.
  access_token_validity  = var.federated_login_enabled ? 10 : 60     # minutes
  id_token_validity      = var.federated_login_enabled ? 60 : 60     # minutes
  refresh_token_validity = var.federated_login_enabled ? 600 : 43200 # minutes (10h vs 30d)

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "minutes"
  }

  # No client secret for SPA (public client)
  generate_secret = false

  # Prevent user existence errors
  prevent_user_existence_errors = "ENABLED"

  # The App Client must wait for the OIDC identity provider to exist before
  # referencing it in supported_identity_providers.
  depends_on = [aws_cognito_identity_provider.federated]

  explicit_auth_flows = concat(
    [
      "ALLOW_REFRESH_TOKEN_AUTH",
      "ALLOW_USER_SRP_AUTH",
    ],
    # Allow simple username/password auth in non-prod for CLI smoke testing
    var.environment != "prod" ? ["ALLOW_USER_PASSWORD_AUTH"] : [],
  )
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Admin group for registry management and admin page access
resource "aws_cognito_user_group" "admins" {
  name         = "admins"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Administrators with full access to all projects and agent registry management"
}

# Standard user group — own projects, all write operations
resource "aws_cognito_user_group" "users" {
  name         = "users"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Standard users with access to their own projects (create, review, chat, delete)"
}

# Read-only viewer group — all projects, read + chat only, no modifications
resource "aws_cognito_user_group" "viewers" {
  name         = "viewers"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Read-only viewers with read access to all projects, plus chat"
}

locals {
  # In dev, include localhost URLs for Vite dev server (port 5173)
  dev_callback_urls = var.environment == "dev" ? [
    "http://localhost:5173/callback",
  ] : []
  dev_logout_urls = var.environment == "dev" ? [
    "http://localhost:5173",
  ] : []

  _merged_callback_urls = distinct(concat(var.callback_urls, local.dev_callback_urls))
  _merged_logout_urls   = distinct(concat(var.logout_urls, local.dev_logout_urls))

  # Cognito requires at least one callback URL when OAuth flows are enabled.
  # On first deploy of non-dev environments, the CloudFront URL isn't known
  # yet (dependency cycle — see main.tf). Use a safe placeholder that gets
  # replaced on the second apply once the CloudFront distribution exists.
  callback_urls = length(local._merged_callback_urls) > 0 ? local._merged_callback_urls : ["https://localhost/callback"]
  logout_urls   = length(local._merged_logout_urls) > 0 ? local._merged_logout_urls : ["https://localhost"]
}
