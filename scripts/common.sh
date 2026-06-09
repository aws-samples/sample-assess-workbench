#!/bin/bash
# Common functions and environment loading for deployment scripts

# Load environment variables from .env if it exists
load_env() {
    if [ -f .env ]; then
        set -a  # automatically export all variables
        source .env
        set +a
        echo "✓ Loaded configuration from .env"
    else
        echo "⚠️  No .env file found, using defaults"
        echo "   Copy .env.example to .env and configure for your environment"
    fi
}

# Set defaults for required variables
set_defaults() {
    export AWS_REGION="${AWS_REGION:-us-west-2}"
    export PYTHON_RUNTIME="${PYTHON_RUNTIME:-PYTHON_3_13}"
    export ENVIRONMENT="${ENVIRONMENT:-dev}"
    export PROJECT_NAME="${PROJECT_NAME:-risk-assessor}"
}

# Check if agentcore CLI is installed
check_agentcore_cli() {
    if ! command -v agentcore &> /dev/null; then
        echo "❌ agentcore CLI is not installed"
        echo "Install with: uv tool install bedrock-agentcore-starter-toolkit"
        exit 1
    fi
    echo "✓ agentcore CLI is installed"
}

# Check AWS credentials
check_aws_credentials() {
    echo "Checking AWS credentials..."
    
    if ! aws sts get-caller-identity &> /dev/null; then
        echo "❌ AWS credentials not configured"
        echo "Configure credentials with: aws configure"
        exit 1
    fi
    
    ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
    
    echo "✓ AWS credentials configured"
    echo "  Region: ${AWS_REGION}"
    echo "  Account: ${ACCOUNT_ID}"
    echo "  User/Role: $(aws sts get-caller-identity --query 'Arn' --output text)"
    
    # Export for use in other scripts
    export AWS_ACCOUNT_ID="${ACCOUNT_ID}"
}

# Initialize - call this at the start of deployment scripts
init_deployment() {
    load_env
    set_defaults
    check_agentcore_cli
    echo ""
    check_aws_credentials
    echo ""
}

# SSM Parameter Store helpers
SSM_PREFIX="/${PROJECT_NAME:-risk-assessor}/${ENVIRONMENT:-dev}"

# Write a value to SSM Parameter Store
ssm_put() {
    local name="$1"
    local value="$2"
    local description="${3:-}"

    # Re-evaluate prefix in case vars were set after sourcing
    local prefix="/${PROJECT_NAME}/${ENVIRONMENT}"

    # Use || return 1 to prevent set -e from aborting the caller;
    # this lets the caller handle the failure gracefully via if/else.
    aws ssm put-parameter \
        --name "${prefix}/${name}" \
        --value "${value}" \
        --type String \
        --overwrite \
        --region "${AWS_REGION}" \
        ${description:+--description "${description}"} \
        > /dev/null 2>&1 || return 1

    echo "  ✓ SSM: ${prefix}/${name}"
}

# Read a value from SSM Parameter Store
ssm_get() {
    local name="$1"
    local prefix="/${PROJECT_NAME}/${ENVIRONMENT}"

    aws ssm get-parameter \
        --name "${prefix}/${name}" \
        --query 'Parameter.Value' \
        --output text \
        --region "${AWS_REGION}" \
        2>/dev/null
}
