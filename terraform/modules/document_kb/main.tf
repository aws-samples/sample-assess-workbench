/**
 * Document Index Knowledge Base Module
 *
 * Creates a Bedrock Knowledge Base with a custom data source backed by
 * S3 Vectors for indexing project documents. Documents are ingested
 * inline via IngestKnowledgeBaseDocuments (no S3 staging bucket needed).
 *
 * One shared KB across all projects — project_id metadata filtering
 * provides isolation at query time.
 *
 * Note: The KB and data source are created via the deploy_document_kb.sh
 * script (AWS CLI) because the Terraform AWS provider does not yet fully
 * support Bedrock KB with custom data sources and S3 Vectors. The KB ID
 * and data source ID are read from SSM parameters written by the script.
 *
 * This module is a passthrough that reads SSM values and exposes them
 * as outputs for other modules — same pattern as the memory module.
 */
