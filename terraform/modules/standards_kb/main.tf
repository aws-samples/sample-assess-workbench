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
