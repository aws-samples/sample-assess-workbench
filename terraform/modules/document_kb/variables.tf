variable "document_kb_id" {
  description = "Bedrock Knowledge Base ID for the Document Index (created via deploy script, read from SSM)"
  type        = string
}

variable "document_ds_id" {
  description = "Bedrock KB data source ID for the Document Index (created via deploy script, read from SSM)"
  type        = string
}
