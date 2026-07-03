# =============================================================================
# WAFv2 WebACL for CloudFront
#
# Must be declared in us-east-1 (the CLOUDFRONT scope is only available there).
# Provides three layers of protection:
#   1. AWS managed rules for common web exploits (SQLi, XSS, etc.)
#   2. AWS managed rules for known-bad inputs (Log4j, path traversal, etc.)
#   3. AWS managed anonymous-IP list (Tor/VPN/proxy in block mode; hosting
#      providers in count mode to avoid blocking corporate/cloud egress)
#   4. Rate limit of 2000 requests per 5 minutes per source IP
#
# Managed rules ship in block mode. If a rule produces false positives,
# override it to count mode in the `rule_action_override` block inside the
# relevant managed_rule_group_statement without destroying the resource.
# =============================================================================

resource "aws_wafv2_web_acl" "cloudfront" {
  provider = aws.us_east_1

  name        = "${var.project_name}-cloudfront-${var.environment}"
  description = "WAF for ${var.project_name} CloudFront distribution - ${var.environment}"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # ----- Rule 1: AWS managed common rule set (OWASP-ish core protections) -----
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        # SizeRestrictions_BODY blocks POST bodies > 8 KB. Our plan approval
        # payload legitimately exceeds this (agent configs, prompt addendums,
        # focus areas). Override to count mode so it logs but doesn't block.
        # Other size protections remain: API Gateway 10 MB limit, Lambda 6 MB.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-cloudfront-common-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  # ----- Rule 2: AWS managed known-bad-inputs rule set ------------------------
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-cloudfront-knownbad-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  # ----- Rule 3: AWS managed anonymous-IP list --------------------------------
  # Blocks requests from known anonymizing sources (Tor, VPNs, proxies). Part of
  # AWS's recommended Log4j mitigation set alongside KnownBadInputs, since
  # exploit scans came heavily from anonymizing infrastructure.
  rule {
    name     = "AWSManagedRulesAnonymousIpList"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAnonymousIpList"
        vendor_name = "AWS"

        # HostingProviderIPList blocks cloud/datacenter IP ranges, which would
        # also catch legitimate users behind corporate VPNs, cloud-hosted
        # browsers, and similar egress. Override to count mode so it logs but
        # doesn't block; the Tor/VPN/proxy anonymizer rules stay in block mode.
        rule_action_override {
          name = "HostingProviderIPList"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-cloudfront-anonip-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  # ----- Rule 4: Per-IP rate limit --------------------------------------------
  # 2000 requests per 5 minutes per source IP (~6.7 req/s sustained). Well
  # above any legitimate user traffic; designed to catch scripted abuse.
  rule {
    name     = "RateLimitPerIP"
    priority = 4

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-cloudfront-ratelimit-${var.environment}"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-cloudfront-webacl-${var.environment}"
    sampled_requests_enabled   = true
  }

  tags = {
    Name      = "${var.project_name}-cloudfront-waf-${var.environment}"
    Component = "frontend-hosting"
  }
}

# ----- WAF logging to CloudWatch Logs ----------------------------------------
#
# CloudWatch log group name for WAFv2 logs MUST start with `aws-waf-logs-`.
# AWS enforces this at the PutLoggingConfiguration API. For dev/demo volume
# CloudWatch is fine; higher volumes should use S3 or Kinesis Firehose.

resource "aws_cloudwatch_log_group" "waf_cloudfront" {
  provider = aws.us_east_1

  name              = "aws-waf-logs-${var.project_name}-cloudfront-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Name      = "${var.project_name}-cloudfront-waf-logs-${var.environment}"
    Component = "frontend-hosting"
  }
}

resource "aws_wafv2_web_acl_logging_configuration" "cloudfront" {
  provider = aws.us_east_1

  resource_arn            = aws_wafv2_web_acl.cloudfront.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf_cloudfront.arn]

  # Redact the Authorization header from logs — even though sampled requests
  # won't include full JWTs by default, this is belt-and-braces.
  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
}
