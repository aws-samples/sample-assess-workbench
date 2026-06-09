# S3 bucket for design documents
resource "aws_s3_bucket" "design_docs" {
  bucket        = "${var.project_name}-design-docs-${var.environment}-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = {
    Name        = "${var.project_name}-design-docs-${var.environment}"
    Environment = var.environment
    Purpose     = "Design document storage"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "design_docs" {
  bucket = aws_s3_bucket.design_docs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Versioning
resource "aws_s3_bucket_versioning" "design_docs" {
  bucket = aws_s3_bucket.design_docs.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Public access block
resource "aws_s3_bucket_public_access_block" "design_docs" {
  bucket = aws_s3_bucket.design_docs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CORS configuration for browser-based uploads via pre-signed URLs
resource "aws_s3_bucket_cors_configuration" "design_docs" {
  bucket = aws_s3_bucket.design_docs.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = var.allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# Lifecycle configuration
resource "aws_s3_bucket_lifecycle_configuration" "design_docs" {
  bucket = aws_s3_bucket.design_docs.id

  rule {
    id     = "delete-old-versions"
    status = "Enabled"

    filter {} # Empty filter applies to all objects

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    filter {} # Empty filter applies to all objects

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {} # Empty filter applies to all objects

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Bucket policy - deny insecure transport
resource "aws_s3_bucket_policy" "design_docs" {
  bucket = aws_s3_bucket.design_docs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.design_docs.arn,
          "${aws_s3_bucket.design_docs.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# CloudWatch log group for S3 access logs (optional)
resource "aws_cloudwatch_log_group" "s3_access" {
  name              = "/aws/s3/${var.project_name}-design-docs"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "${var.project_name}-s3-access-logs"
    Environment = var.environment
  }
}

# SSM parameter to store bucket name
resource "aws_ssm_parameter" "bucket_name" {
  name        = "/${var.project_name}/${var.environment}/design-docs-bucket"
  description = "S3 bucket name for design documents"
  type        = "String"
  value       = aws_s3_bucket.design_docs.id

  tags = {
    Environment = var.environment
    Project     = var.project_name
  }
}

data "aws_caller_identity" "current" {}
