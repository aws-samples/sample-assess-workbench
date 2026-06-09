# Outputs for adaptive workflow module

output "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = aws_sfn_state_machine.review_workflow.arn
}

output "state_machine_name" {
  description = "Name of the Step Functions state machine"
  value       = aws_sfn_state_machine.review_workflow.name
}

output "load_document_function_name" {
  description = "Name of the load document Lambda function"
  value       = aws_lambda_function.load_document.function_name
}

output "plan_review_function_name" {
  description = "Name of the plan review Lambda function"
  value       = aws_lambda_function.plan_review.function_name
}

output "invoke_review_agent_function_name" {
  description = "Name of the invoke review agent Lambda function"
  value       = aws_lambda_function.invoke_review_agent.function_name
}

output "aggregate_results_function_name" {
  description = "Name of the aggregate results Lambda function"
  value       = aws_lambda_function.aggregate_results.function_name
}

output "store_plan_function_name" {
  description = "Name of the store plan Lambda function"
  value       = aws_lambda_function.store_plan.function_name
}

output "invoke_judge_function_name" {
  description = "Name of the invoke judge Lambda function"
  value       = aws_lambda_function.invoke_judge.function_name
}

output "merge_quality_function_name" {
  description = "Name of the merge quality Lambda function"
  value       = aws_lambda_function.merge_quality.function_name
}

output "run_benchmark_function_name" {
  description = "Name of the benchmark runner Lambda function"
  value       = aws_lambda_function.run_benchmark.function_name
}

output "run_benchmark_function_arn" {
  description = "ARN of the benchmark runner Lambda function"
  value       = aws_lambda_function.run_benchmark.arn
}
