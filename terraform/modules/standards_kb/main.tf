/**
 * Standards Knowledge Base Module
 *
 * Creates a Bedrock Knowledge Base with an S3 data source backed by
 * S3 Vectors for compliance standards reference material. Standards
 * are markdown files in S3 with JSON metadata sidecars.
 *
 * Separate from the Document Index KB — different lifecycle, different
 * access patterns. Standards are global reference material managed by
 * corpus administrators; project documents are per-review and scoped
 * to project lifecycle.
 *
 * Note: The KB, S3 bucket, and data source are created via the
 * deploy_standards_kb.sh script (AWS CLI) because the Terraform AWS
 * provider does not yet fully support Bedrock KB with S3 Vectors.
 * The KB ID is read from SSM and exposed as an output.
 *
 * This module is a passthrough — same pattern as the memory and
 * document_kb modules.
 */
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# APPLICATION_LOGS delivery for the Standards KB: per-file status during
# ingestion jobs (indexed / skipped / failed). Turns a silent empty-index
# sync into a diagnosable event. The KB itself is CLI-managed (S3 Vectors,
# not TF-supported), but log delivery is standard CloudWatch and references
# the KB by ARN. The /aws/vendedlogs/ prefix is auto-authorized for the
# delivery service, so no log-group resource policy is needed.
resource "aws_cloudwatch_log_group" "kb_application" {
  name              = "/aws/vendedlogs/bedrock/${var.project_name}-standards-kb-${var.environment}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "kb_application" {
  name         = "${var.project_name}-standards-kb-${var.environment}-app-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = "arn:aws:bedrock:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:knowledge-base/${var.standards_kb_id}"
}

resource "aws_cloudwatch_log_delivery_destination" "kb_application" {
  name          = "${var.project_name}-standards-kb-${var.environment}-app-logs"
  output_format = "json"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.kb_application.arn
  }
}

resource "aws_cloudwatch_log_delivery" "kb_application" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.kb_application.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.kb_application.arn
}
