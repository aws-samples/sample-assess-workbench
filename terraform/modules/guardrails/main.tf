/**
 * Bedrock Guardrails Module
 *
 * Creates a single Bedrock Guardrail with PII redaction and content filtering
 * for review and chat agents. Workflow Lambdas (planner, judge, image analysis,
 * benchmarks) are excluded — they are internal orchestration steps.
 *
 * The guardrail ID and version are written to SSM for the deploy script
 * (scripts/deploy_agent.sh) to pass as environment variables to AgentCore
 * runtimes. IAM permissions (bedrock:ApplyGuardrail) are granted separately
 * by scripts/grant_agent_permissions.sh after agent deployment.
 */

locals {
  ssm_prefix = "/${var.project_name}/${var.environment}"
}

# ── Guardrail resource ────────────────────────────────────────────

resource "aws_bedrock_guardrail" "agents" {
  name                      = "${var.project_name}-${var.environment}-guardrail"
  description               = "PII redaction and content filtering for review and chat agents"
  blocked_input_messaging   = "Your input was blocked by our content policy."
  blocked_outputs_messaging = "The response was blocked by our content policy."

  # Content filters — HIGH threshold to avoid false positives on legitimate
  # compliance/security content (vulnerability descriptions, attack vectors,
  # regulatory citations about data breaches, etc.).
  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    # PROMPT_ATTACK removed: review agents send entire documents as input,
    # and chat agents pull document excerpts and regulatory standards via
    # tools. Compliance/regulatory text is full of directive language
    # ("you must ensure", "organizations shall implement") that triggers
    # false positives even at HIGH threshold. The attack surface this
    # filter protects against doesn't apply here — inputs are server-
    # controlled prompts, authenticated user messages, or content from
    # our own S3 buckets.
  }

  # PII redaction — anonymize PII in model outputs. Customer documents may
  # contain PII that leaks into findings or chat responses.
  # NAME and AGE are excluded: too many false positives in compliance context
  # (regulation authors, standard names, age thresholds in regulations).
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "US_SOCIAL_SECURITY_NUMBER"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "ADDRESS"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "AWS_ACCESS_KEY"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "AWS_SECRET_KEY"
      action = "ANONYMIZE"
    }
  }
}

# Versioned snapshot — agents reference a specific version, not DRAFT.
resource "aws_bedrock_guardrail_version" "v1" {
  guardrail_arn = aws_bedrock_guardrail.agents.guardrail_arn
  description   = "v2 — PII redaction + HIGH content filters, PROMPT_ATTACK removed"
}

# ── SSM parameters ────────────────────────────────────────────────
# deploy_agent.sh reads these to pass GUARDRAIL_ID / GUARDRAIL_VERSION
# as env vars to AgentCore runtimes. grant_agent_permissions.sh reads
# guardrail/id to construct the ARN for the IAM policy.

resource "aws_ssm_parameter" "guardrail_id" {
  name        = "${local.ssm_prefix}/guardrail/id"
  type        = "String"
  value       = aws_bedrock_guardrail.agents.guardrail_id
  description = "Bedrock Guardrail ID for review and chat agents"
  overwrite   = true
}

resource "aws_ssm_parameter" "guardrail_version" {
  name        = "${local.ssm_prefix}/guardrail/version"
  type        = "String"
  value       = aws_bedrock_guardrail_version.v1.version
  description = "Bedrock Guardrail version for review and chat agents"
  overwrite   = true
}
