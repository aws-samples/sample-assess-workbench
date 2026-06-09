output "user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "Cognito User Pool ARN"
  value       = aws_cognito_user_pool.main.arn
}

output "user_pool_endpoint" {
  description = "Cognito User Pool endpoint"
  value       = aws_cognito_user_pool.main.endpoint
}

output "client_id" {
  description = "Cognito App Client ID"
  value       = aws_cognito_user_pool_client.frontend.id
}

output "domain" {
  description = "Cognito Hosted UI domain"
  value       = aws_cognito_user_pool_domain.main.domain
}

output "hosted_ui_url" {
  description = "Full Cognito Hosted UI login URL"
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

output "issuer_url" {
  description = "JWT issuer URL for API Gateway authorizer"
  value       = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

output "federated_secret_name" {
  description = "Secrets Manager secret name for the OIDC client secret (empty when federation disabled)"
  value       = var.federated_login_enabled ? aws_secretsmanager_secret.federated_client_secret[0].name : ""
}
