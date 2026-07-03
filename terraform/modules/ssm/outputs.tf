# Shared memory ARN read from SSM
output "shared_memory_arn" {
  value = data.aws_ssm_parameter.shared_memory_arn.value
}

# Document Index KB IDs read from SSM
output "document_kb_id" {
  value = data.aws_ssm_parameter.document_kb_id.value
}

output "document_ds_id" {
  value = data.aws_ssm_parameter.document_ds_id.value
}

# Standards KB ID and Data Source ID read from SSM
output "standards_kb_id" {
  value = data.aws_ssm_parameter.standards_kb_id.value
}

output "standards_ds_id" {
  value = data.aws_ssm_parameter.standards_ds_id.value
}
