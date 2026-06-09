# =============================================================================
# Edge Module: S3 + CloudFront + WAF + optional API/WebSocket proxy
#
# Provides the frontend hosting infrastructure as an optional module within the
# main Terraform stack. Controlled by the parent's `deploy_frontend` variable.
#
# When `enable_api_proxy` is true (staging/prod), the CloudFront distribution
# also proxies API and WebSocket traffic — unified ingress with WAF in front.
# When false (dev), the distribution serves only the SPA static assets.
#
# S3 bucket lives in the caller's region (default provider); CloudFront, the
# response headers policy, WAFv2, and CloudFront Functions live in us-east-1
# (aws.us_east_1 alias) because CloudFront resources must be declared there.
# =============================================================================

data "aws_caller_identity" "current" {}

locals {
  # AWS managed cache policy IDs (opaque UUIDs → named locals for readability)
  cache_policy_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
  cache_policy_disabled  = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled

  # AWS managed origin request policy IDs
  # AllViewerExceptHostHeader forwards all viewer headers (including Authorization),
  # query strings, and cookies to the origin — except the Host header, which
  # CloudFront replaces with the origin domain. This is the recommended policy
  # for API proxying. Authorization cannot be whitelisted in a custom origin
  # request policy (it's a restricted header), so the managed policy is required.
  origin_request_all_viewer_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader

  # When API proxy is enabled (staging/prod), API and WebSocket traffic is
  # same-origin through CloudFront — no execute-api wildcards needed in CSP.
  # The Cognito hosted UI URL must always be included because the OAuth
  # /oauth2/token code-exchange fetch is cross-origin.
  connect_src = var.enable_api_proxy ? join(" ", [
    "'self'",
    var.cognito_hosted_ui_url,
    "https://${var.design_docs_bucket_domain}",
    ]) : join(" ", [
    "'self'",
    "https://*.execute-api.${var.aws_region}.amazonaws.com",
    "wss://*.execute-api.${var.aws_region}.amazonaws.com",
    var.cognito_hosted_ui_url,
    "https://${var.design_docs_bucket_domain}",
  ])

  # Parse domain from full endpoint URLs for CloudFront origins.
  # API: "https://abc123.execute-api.us-west-2.amazonaws.com/v1" → "abc123.execute-api..."
  # WS:  "pynhbvlqw1.execute-api.us-west-2.amazonaws.com" (passed as domain-only from parent)
  api_origin_domain = var.enable_api_proxy ? replace(replace(var.api_gateway_endpoint, "/^https?:\\/\\//", ""), "/\\/.*$/", "") : ""
  ws_origin_domain  = var.enable_api_proxy ? var.websocket_endpoint : ""
}

# ---------- S3 bucket (default provider, var.aws_region) ----------------------

resource "aws_s3_bucket" "frontend" {
  bucket        = "${var.project_name}-frontend-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "prod"

  tags = {
    Name      = "${var.project_name}-frontend-${var.environment}"
    Component = "frontend-hosting"
    Purpose   = "Frontend SPA hosting"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------- CloudFront Origin Access Control (us-east-1) ----------------------

resource "aws_cloudfront_origin_access_control" "frontend" {
  provider = aws.us_east_1

  name                              = "${var.project_name}-frontend-${var.environment}"
  description                       = "OAC for the frontend SPA bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ---------- CloudFront Functions (us-east-1) ----------------------------------

# SPA rewrite: non-asset paths → /index.html (replaces custom_error_response)
# This is always present — the SPA needs client-side routing regardless of
# whether API proxy is enabled.
resource "aws_cloudfront_function" "spa_rewrite" {
  provider = aws.us_east_1

  name    = "${var.project_name}-spa-rewrite-${var.environment}"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite non-asset paths to /index.html for SPA client-side routing"
  publish = true
  code    = <<-EOF
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      // Real assets (JS, CSS, images, config.json, etc.) — pass through
      if (uri.includes('.')) {
        return request;
      }
      // Client-side routes (/projects/abc, /settings, etc.) — serve index.html
      request.uri = '/index.html';
      return request;
    }
  EOF
}

# API path rewrite: /api/* → /v1/* (only when API proxy is enabled)
resource "aws_cloudfront_function" "api_rewrite" {
  count    = var.enable_api_proxy ? 1 : 0
  provider = aws.us_east_1

  name    = "${var.project_name}-api-rewrite-${var.environment}"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite /api/* to /v1/* for API Gateway stage routing"
  publish = true
  code    = <<-EOF
    function handler(event) {
      var request = event.request;
      // /api/projects → /v1/projects
      request.uri = request.uri.replace(/^\/api/, '/v1');
      return request;
    }
  EOF
}

# WebSocket path rewrite: /ws → /${environment} (only when API proxy is enabled)
# The WebSocket API Gateway stage expects the upgrade at exactly /${environment}
# with no trailing slash. We handle the full path rewrite in the CF Function
# rather than using origin_path, because origin_path + "/" produces a trailing
# slash that causes a route mismatch (403 with routeKey "-").
resource "aws_cloudfront_function" "ws_rewrite" {
  count    = var.enable_api_proxy ? 1 : 0
  provider = aws.us_east_1

  name    = "${var.project_name}-ws-rewrite-${var.environment}"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite /ws to /${var.environment} for WebSocket API Gateway routing"
  publish = true
  code    = <<-EOF
    function handler(event) {
      var request = event.request;
      if (request.uri === '/ws') {
        request.uri = '/${var.environment}';
      }
      return request;
    }
  EOF
}

# ---------- CloudFront response headers policies (us-east-1) -----------------

# Full security headers with CSP — for SPA HTML responses only
resource "aws_cloudfront_response_headers_policy" "security" {
  provider = aws.us_east_1

  name    = "${var.project_name}-security-headers-${var.environment}"
  comment = "Security headers (CSP, HSTS, frame/content-type protections) for the SPA"

  security_headers_config {
    content_security_policy {
      content_security_policy = join("; ", [
        "default-src 'self'",
        "connect-src ${local.connect_src}",
        # Vite injects inline styles at runtime; 'unsafe-inline' required for styles.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ])
      override = true
    }

    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

# Minimal security headers for API responses — no CSP (only meaningful for HTML)
resource "aws_cloudfront_response_headers_policy" "api_security" {
  count    = var.enable_api_proxy ? 1 : 0
  provider = aws.us_east_1

  name    = "${var.project_name}-api-security-headers-${var.environment}"
  comment = "Security headers for API responses (no CSP — only meaningful for HTML)"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

# ---------- Origin request policies (us-east-1) ------------------------------

# WebSocket: forward upgrade headers and query strings (token) to WebSocket API.
# The API origin uses the managed AllViewerExceptHostHeader policy instead of a
# custom policy because Authorization is a restricted header that cannot be
# whitelisted in custom origin request policies.
resource "aws_cloudfront_origin_request_policy" "websocket_forward" {
  count    = var.enable_api_proxy ? 1 : 0
  provider = aws.us_east_1

  name    = "${var.project_name}-ws-forward-${var.environment}"
  comment = "Forward WebSocket headers and query strings to WebSocket API Gateway"

  # Note: The Upgrade and Connection headers required for WebSocket are handled
  # transparently by CloudFront — they do not need to be (and cannot be)
  # whitelisted here. CloudFront detects the 101 Switching Protocols response
  # from the origin and upgrades the viewer connection automatically.
  headers_config {
    header_behavior = "whitelist"
    headers {
      items = [
        "Sec-WebSocket-Key",
        "Sec-WebSocket-Version",
        "Sec-WebSocket-Protocol",
        "Sec-WebSocket-Extensions",
      ]
    }
  }

  query_strings_config {
    query_string_behavior = "all" # token is passed as ?token=<jwt>
  }

  cookies_config {
    cookie_behavior = "none"
  }
}

# ---------- CloudFront distribution (us-east-1) -------------------------------

resource "aws_cloudfront_distribution" "frontend" {
  provider = aws.us_east_1

  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.project_name} frontend (${var.environment})${var.enable_api_proxy ? " + API proxy" : ""}"
  default_root_object = "index.html"
  price_class         = var.price_class
  http_version        = "http2"
  web_acl_id          = aws_wafv2_web_acl.cloudfront.arn

  # ----- Origin: S3 frontend (always present) -----
  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # ----- Origin: API Gateway HTTP API (staging/prod only) -----
  # No origin_path — path rewriting (/api/* → /v1/*) is handled by the
  # api_rewrite CloudFront Function on the cache behavior.
  dynamic "origin" {
    for_each = var.enable_api_proxy ? [1] : []
    content {
      domain_name = local.api_origin_domain
      origin_id   = "api-gateway"

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }

      custom_header {
        name  = "X-Origin-Verify"
        value = var.origin_verify_secret
      }
    }
  }

  # ----- Origin: WebSocket API Gateway (staging/prod only) -----
  dynamic "origin" {
    for_each = var.enable_api_proxy ? [1] : []
    content {
      domain_name = local.ws_origin_domain
      origin_id   = "websocket-api"
      # No origin_path — the CF Function rewrites /ws → /${environment} directly.
      # Using origin_path = "/${environment}" combined with uri "/" produces
      # "/${environment}/" which fails WebSocket route matching (trailing slash).

      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }

      custom_header {
        name  = "X-Origin-Verify"
        value = var.origin_verify_secret
      }
    }
  }

  # ----- Default behavior: S3 SPA assets (content-hashed, long cache) -----
  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id            = local.cache_policy_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  # ----- Behavior: /index.html (never cached) -----
  ordered_cache_behavior {
    path_pattern           = "/index.html"
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id            = local.cache_policy_disabled
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # ----- Behavior: /config.json (never cached, Terraform-generated) -----
  ordered_cache_behavior {
    path_pattern           = "/config.json"
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    cache_policy_id            = local.cache_policy_disabled
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # ----- Behavior: /api/* → API Gateway (staging/prod only) -----
  dynamic "ordered_cache_behavior" {
    for_each = var.enable_api_proxy ? [1] : []
    content {
      path_pattern           = "/api/*"
      target_origin_id       = "api-gateway"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods         = ["GET", "HEAD"]
      compress               = true

      # No caching — forward everything to origin
      cache_policy_id          = local.cache_policy_disabled
      origin_request_policy_id = local.origin_request_all_viewer_except_host

      # Minimal security headers (HSTS, X-Frame-Options, etc.) — no CSP on JSON
      response_headers_policy_id = aws_cloudfront_response_headers_policy.api_security[0].id

      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.api_rewrite[0].arn
      }
    }
  }

  # ----- Behavior: /ws → WebSocket API Gateway (staging/prod only) -----
  dynamic "ordered_cache_behavior" {
    for_each = var.enable_api_proxy ? [1] : []
    content {
      path_pattern           = "/ws"
      target_origin_id       = "websocket-api"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods         = ["GET", "HEAD"]
      compress               = false

      cache_policy_id          = local.cache_policy_disabled
      origin_request_policy_id = aws_cloudfront_origin_request_policy.websocket_forward[0].id

      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.ws_rewrite[0].arn
      }
    }
  }

  # SPA routing is now handled by the spa_rewrite CloudFront Function on the
  # default behavior. No custom_error_response blocks — those would intercept
  # legitimate API 403/404 JSON responses when API proxy is enabled.

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name      = "${var.project_name}-frontend-${var.environment}"
    Component = "frontend-hosting"
  }
}

# ---------- S3 bucket policy granting CloudFront OAC read access --------------

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipalReadOnly"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.frontend.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.frontend.arn,
          "${aws_s3_bucket.frontend.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}
