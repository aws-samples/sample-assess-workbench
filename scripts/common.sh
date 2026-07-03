#!/bin/bash
# Common functions and environment loading for deployment scripts

# Load environment and resolve the active environment.
#
# Delegates to the single source of truth, scripts/utils/with-env.sh, which
# loads .env (a per-command ENVIRONMENT=/PROJECT_NAME=/AWS_REGION= override wins
# over the file), runs the account guard, and exports the resolved values.
# Never `source .env` by hand — this is the one loader.
load_env() {
    local _cs_dir
    _cs_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck source=scripts/utils/with-env.sh
    source "${_cs_dir}/utils/with-env.sh"
}

# Require the tenant/runtime knobs — no silent defaults. The direct-invocation
# counterpart of Taskfile check:env: a misconfigured .env fails loud here too,
# rather than masking itself behind a fallback that equals the shipped value.
require_env() {
    : "${AWS_REGION:?AWS_REGION must be set (see .env.example)}"
    : "${ENVIRONMENT:?ENVIRONMENT must be set (see .env.example)}"
    : "${PROJECT_NAME:?PROJECT_NAME must be set (see .env.example)}"
    : "${PYTHON_RUNTIME:?PYTHON_RUNTIME must be set (see .env.example)}"
}

# Canonical name of the shared semantic memory; single source of truth.
# Hyphens map to underscores: AgentCore memory names allow [A-Za-z0-9_] only.
# Fails if PROJECT_NAME/ENVIRONMENT are unset rather than guessing a name.
shared_memory_name() {
    : "${PROJECT_NAME:?shared_memory_name: PROJECT_NAME must be set}"
    : "${ENVIRONMENT:?shared_memory_name: ENVIRONMENT must be set}"
    echo "${PROJECT_NAME//-/_}_shared_memory_${ENVIRONMENT}"
}

# True if an AWS CLI error string denotes a missing resource — an idempotent
# already-deleted — rather than a real failure worth surfacing. Used by the
# teardown scripts to keep "already gone" quiet while failing loud on the rest.
is_not_found() {
    printf '%s' "$1" | grep -qiE 'NotFound|ResourceNotFound|NoSuchBucket|NoSuchEntity|does not exist|could not be found'
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
    require_env
    check_agentcore_cli
    echo ""
    check_aws_credentials
    echo ""
}

# SSM Parameter Store helpers

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
