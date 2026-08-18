output "bucket_name" {
  description = "S3 bucket name"
  value       = aws_s3_bucket.design_docs.id
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.design_docs.arn
}

output "bucket_domain_name" {
  description = "S3 bucket domain name"
  value       = aws_s3_bucket.design_docs.bucket_domain_name
}

output "bucket_regional_domain_name" {
  description = "S3 bucket regional domain name (used by pre-signed URLs)"
  value       = aws_s3_bucket.design_docs.bucket_regional_domain_name
}

output "ssm_parameter_name" {
  description = "SSM parameter name containing bucket name"
  value       = aws_ssm_parameter.bucket_name.name
}
