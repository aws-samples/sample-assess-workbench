variable "standards_kb_id" {
  description = "Bedrock Knowledge Base ID for the Standards KB (created via deploy script, read from SSM)"
  type        = string
}

variable "standards_ds_id" {
  description = "Bedrock KB data source ID for the Standards KB (created via deploy script, read from SSM)"
  type        = string
}
