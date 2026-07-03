variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "callback_urls" {
  description = "Allowed callback URLs for OAuth (frontend URLs)"
  type        = list(string)
  default     = ["http://localhost:8080/callback.html"]
}

variable "logout_urls" {
  description = "Allowed logout URLs"
  type        = list(string)
  default     = ["http://localhost:8080"]
}

# Optional OIDC federation variables.
#
# All default to OFF, so a stock deploy uses the Cognito native user pool only.
# To federate with a standard OIDC provider (Okta, Entra ID, Google, etc.), set
# these and provide the client secret via federated_client_secret (injected at
# deploy time, never committed).

variable "federated_login_enabled" {
  description = "Enable optional OIDC federation. When false (default), only the native Cognito user pool is used."
  type        = bool
  default     = false
}

variable "federated_identity_provider" {
  description = "Cognito identity provider name for the OIDC provider (e.g. the name shown in the hosted UI)."
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
