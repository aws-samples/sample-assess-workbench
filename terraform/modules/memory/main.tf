/**
 * AgentCore Memory Module
 * 
 * Manages shared memory resource ARN for all agents and projects.
 * Memory resource is created via AgentCore CLI (scripts/deploy_shared_memory.sh)
 * and ARN is passed as a variable.
 * 
 * Note: AWS Terraform provider does not yet support aws_bedrock_agentcore_memory resource.
 */

# No resources to create - memory is managed via AgentCore CLI
# The memory ARN is passed as a variable and used by other modules
