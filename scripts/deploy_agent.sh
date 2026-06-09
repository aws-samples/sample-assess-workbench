#!/bin/bash
# Deploy a single agent to AgentCore.
# Usage: bash scripts/deploy_agent.sh <agent_name>
#
# Agents are discovered from agents/*/agent.yaml files.
# Each agent.yaml defines: name, role (review|chat), ssm_key, model_id.
#
# Review agents deploy with --disable-memory.
# Model IDs come from the agent registry (DynamoDB), not env vars.

set -e

source "$(dirname "$0")/common.sh"

SCRIPT_DIR="$(dirname "$0")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Discover agents from agent.yaml files ──────────────────────────
discover_agents() {
    local yaml_files
    yaml_files=$(find "${REPO_ROOT}/agents" -name "agent.yaml" -type f 2>/dev/null | sort)
    if [ -z "$yaml_files" ]; then
        echo "❌ No agent.yaml files found in agents/*/"
        exit 1
    fi

    DISCOVERED_AGENTS=()
    DISCOVERED_REVIEW=()
    DISCOVERED_CHAT=()

    while IFS= read -r yaml_file; do
        local dir
        dir=$(dirname "$yaml_file")
        local rel_dir
        rel_dir=$(python3 -c "import os; print(os.path.relpath('${dir}', '${REPO_ROOT}'))")

        # Parse YAML with Python (no yq dependency)
        local agent_name agent_role agent_ssm agent_type_id
        eval "$(python3 -c "
import yaml, sys
with open('${yaml_file}') as f:
    cfg = yaml.safe_load(f)
print(f'agent_name=\"{cfg[\"name\"]}\"')
print(f'agent_role=\"{cfg[\"role\"]}\"')
print(f'agent_ssm=\"{cfg[\"ssm_key\"]}\"')
reg = cfg.get('registry', {})
print(f'agent_type_id=\"{reg.get(\"agent_type\", cfg[\"name\"])}\"')
")"

        DISCOVERED_AGENTS+=("${agent_name}|${rel_dir}|${agent_ssm}|${agent_role}|${agent_type_id}")
        if [ "$agent_role" = "review" ]; then
            DISCOVERED_REVIEW+=("$agent_name")
        elif [ "$agent_role" = "chat" ]; then
            DISCOVERED_CHAT+=("$agent_name")
        fi
    done <<< "$yaml_files"
}

# ── Lookup agent metadata ──────────────────────────────────────────
lookup_agent() {
    local name="$1"
    for entry in "${DISCOVERED_AGENTS[@]}"; do
        IFS='|' read -r a_name a_dir a_ssm a_role a_type <<< "$entry"
        if [ "$a_name" = "$name" ]; then
            AGENT_NAME="$a_name"
            AGENT_DIR="$a_dir"
            AGENT_SSM="$a_ssm"
            AGENT_ROLE="$a_role"
            AGENT_TYPE_ID="$a_type"
            return 0
        fi
    done
    return 1
}

# ── Usage ──────────────────────────────────────────────────────────
usage() {
    echo "Usage: bash scripts/deploy_agent.sh <agent_name>"
    echo ""
    echo "Available agents (discovered from agents/*/agent.yaml):"
    echo ""
    if [ ${#DISCOVERED_REVIEW[@]} -gt 0 ]; then
        echo "  Review agents:"
        for name in "${DISCOVERED_REVIEW[@]}"; do
            printf "    %-25s\n" "$name"
        done
        echo ""
    fi
    if [ ${#DISCOVERED_CHAT[@]} -gt 0 ]; then
        echo "  Chat agents:"
        for name in "${DISCOVERED_CHAT[@]}"; do
            printf "    %-25s\n" "$name"
        done
        echo ""
    fi
    echo "  Special:"
    echo "    all                    Deploy all agents sequentially"
    echo "    review                 Deploy all review agents"
    echo "    chat                   Deploy all chat agents"
    exit 1
}

# ── Deploy a single agent ─────────────────────────────────────────
deploy_one() {
    local name="$1"

    if ! lookup_agent "$name"; then
        echo "❌ Unknown agent: $name"
        echo ""
        usage
    fi

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Deploying: ${AGENT_NAME} (${AGENT_ROLE})"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Copy shared runtime into agent directory so agentcore packages it.
    # The generic agents import from shared.* — the shared/ directory
    # must be a sibling of the entrypoint at deploy time.
    # Only copy the relevant entrypoint + shared modules, not both agents.
    echo "Copying shared runtime into ${AGENT_DIR}..."
    rm -rf "${AGENT_DIR}/shared"
    mkdir -p "${AGENT_DIR}/shared"
    cp agents/shared/__init__.py "${AGENT_DIR}/shared/"
    cp agents/shared/registry_loader.py "${AGENT_DIR}/shared/"
    cp agents/shared/metrics.py "${AGENT_DIR}/shared/"
    # Both roles need hooks.py (LimitToolCounts) and tools/ (agent tools).
    # Phase 2d wired tools into review agents — they need the same shared
    # modules that chat agents have always had.
    cp agents/shared/hooks.py "${AGENT_DIR}/shared/"
    cp -r agents/shared/tools "${AGENT_DIR}/shared/"
    if [ "$AGENT_ROLE" = "review" ]; then
        cp agents/shared/review_agent.py "${AGENT_DIR}/shared/"
        cp agents/shared/schema_builder.py "${AGENT_DIR}/shared/"
    elif [ "$AGENT_ROLE" = "chat" ]; then
        cp agents/shared/chat_agent.py "${AGENT_DIR}/shared/"
    fi
    echo "✓ Shared runtime copied"
    echo ""

    # Resolve the entrypoint based on role
    local entrypoint
    if [ "$AGENT_ROLE" = "review" ]; then
        entrypoint="${AGENT_DIR}/shared/review_agent.py"
    elif [ "$AGENT_ROLE" = "chat" ]; then
        entrypoint="${AGENT_DIR}/shared/chat_agent.py"
    else
        echo "❌ Unknown agent role: ${AGENT_ROLE}"
        return 1
    fi

    # Resolve PROJECTS_TABLE from SSM (same logic as seed_agent_registry.sh)
    local projects_table
    projects_table=$(ssm_get "dynamodb-table" 2>/dev/null || echo "${PROJECT_NAME}-projects-${ENVIRONMENT}")

    # Configure
    echo "Configuring ${AGENT_NAME}..."
    local configure_args=(
        --entrypoint "${entrypoint}"
        --name "${AGENT_NAME}"
        --requirements-file "${AGENT_DIR}/requirements.txt"
        --runtime "${PYTHON_RUNTIME}"
        --non-interactive
    )

    if [ "$AGENT_ROLE" = "review" ]; then
        configure_args+=(--disable-memory)
    fi

    agentcore configure "${configure_args[@]}"
    echo "✓ Configuration complete"
    echo ""

    # Deploy
    echo "Deploying ${AGENT_NAME} to ${AWS_REGION}..."
    local deploy_args=(--agent "${AGENT_NAME}")

    # All agents get AGENT_TYPE and PROJECTS_TABLE for registry lookup
    deploy_args+=(--env AGENT_TYPE="${AGENT_TYPE_ID}")
    deploy_args+=(--env PROJECTS_TABLE="${projects_table}")
    deploy_args+=(--env AWS_REGION="${AWS_REGION}")
    deploy_args+=(--env AWS_DEFAULT_REGION="${AWS_REGION}")

    # Guardrail env vars — conditional on SSM parameter existence.
    # When the guardrail Terraform module hasn't been applied yet,
    # these SSM params won't exist and agents deploy without guardrails.
    local guardrail_id
    guardrail_id=$(ssm_get "guardrail/id" 2>/dev/null || echo "")
    if [ -n "$guardrail_id" ]; then
        local guardrail_version
        guardrail_version=$(ssm_get "guardrail/version" 2>/dev/null || echo "DRAFT")
        deploy_args+=(--env GUARDRAIL_ID="${guardrail_id}")
        deploy_args+=(--env GUARDRAIL_VERSION="${guardrail_version}")
        echo "  Guardrail: ${guardrail_id} (version ${guardrail_version})"

        # Guardrail events table — chat agents persist intervention events
        if [ "$AGENT_ROLE" = "chat" ]; then
            local guardrail_events_table
            guardrail_events_table=$(ssm_get "guardrail-events-table" 2>/dev/null || echo "")
            if [ -n "$guardrail_events_table" ]; then
                deploy_args+=(--env GUARDRAIL_EVENTS_TABLE="${guardrail_events_table}")
                echo "  Guardrail events table: ${guardrail_events_table}"
            fi
        fi
    fi

    agentcore deploy "${deploy_args[@]}"
    echo "✓ Deployment complete"
    echo ""

    # Store ARN in SSM
    echo "Storing agent ARN in SSM..."
    local agent_arn
    agent_arn=$(python3 -c "
import yaml
with open('.bedrock_agentcore.yaml') as f:
    cfg = yaml.safe_load(f)
arn = cfg.get('agents', {}).get('${AGENT_NAME}', {}).get('bedrock_agentcore', {}).get('agent_arn', '')
if arn:
    print(arn)
" 2>/dev/null) || agent_arn=""
    if [ -n "$agent_arn" ]; then
        if ! ssm_put "${AGENT_SSM}" "${agent_arn}" "${AGENT_NAME} agent ARN"; then
            echo "  ⚠️  Agent deployed successfully but SSM update failed (credentials may have expired)"
            echo "  Run manually after refreshing credentials:"
            echo "    aws ssm put-parameter --name \"/${PROJECT_NAME}/${ENVIRONMENT}/${AGENT_SSM}\" --value \"${agent_arn}\" --type String --overwrite --region ${AWS_REGION}"
        fi
    else
        echo "  ⚠️  Could not retrieve agent ARN"
        echo "  Check: agentcore status --agent ${AGENT_NAME} --verbose"
    fi

    echo ""
}

# ── Main ──────────────────────────────────────────────────────────
if [ $# -eq 0 ]; then
    discover_agents
    usage
fi

TARGET="$1"

# Initialize (loads .env, checks CLI and credentials)
init_deployment

# Discover agents from agent.yaml files
discover_agents

case "$TARGET" in
    all)
        echo "Deploying all ${#DISCOVERED_AGENTS[@]} agents..."
        echo ""
        FAILED=()
        for name in "${DISCOVERED_REVIEW[@]}" "${DISCOVERED_CHAT[@]}"; do
            if deploy_one "$name"; then
                echo "✓ ${name} succeeded"
            else
                echo "✗ ${name} failed"
                FAILED+=("$name")
            fi
            echo ""
        done
        if [ ${#FAILED[@]} -eq 0 ]; then
            echo "All agents deployed successfully ✓"
        else
            echo "${#FAILED[@]} agent(s) failed: ${FAILED[*]}"
            exit 1
        fi
        ;;
    review)
        echo "Deploying all review agents..."
        echo ""
        for name in "${DISCOVERED_REVIEW[@]}"; do
            deploy_one "$name"
        done
        echo "All review agents deployed ✓"
        ;;
    chat)
        echo "Deploying all chat agents..."
        echo ""
        for name in "${DISCOVERED_CHAT[@]}"; do
            deploy_one "$name"
        done
        echo "All chat agents deployed ✓"
        ;;
    *)
        deploy_one "$TARGET"
        echo "=================================="
        echo "Deployment successful ✓"
        echo "=================================="
        ;;
esac
