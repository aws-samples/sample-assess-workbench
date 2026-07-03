output "guardrail_arn" {
  description = "ARN of the Bedrock Guardrail"
  value       = aws_bedrock_guardrail.agents.guardrail_arn
}

output "guardrail_id" {
  description = "ID of the Bedrock Guardrail"
  value       = aws_bedrock_guardrail.agents.guardrail_id
}

output "guardrail_version" {
  description = "Published version number of the Bedrock Guardrail"
  value       = aws_bedrock_guardrail_version.v1.version
}
