#!/bin/bash
# Grant AgentCore execution roles the IAM permissions they need.
#
# Policies managed:
#   1. RegistryAccess — dynamodb:GetItem on the projects table (all agents).
#      The generic runtime loads config from the DynamoDB agent registry at
#      startup. Without this, agents fail with AccessDeniedException.
#   2. SharedMemoryAccess — bedrock-agentcore:RetrieveMemoryRecords on the
#      shared semantic memory (all agents). Review agents read prior findings
#      via get_prior_findings; chat agents read findings to answer questions.
#   3. KnowledgeBaseAccess — bedrock:Retrieve on the Document and Standards KBs
#      (all agents, conditional on the KB SSM parameters existing). Review and
#      chat runtimes call it via search_document and lookup_standard.
#   4. GuardrailAccess — bedrock:ApplyGuardrail on the Bedrock guardrail
#      (all agents, conditional). Only granted when the guardrail SSM
#      parameter exists (i.e. the guardrails Terraform module is applied).
#   5. GuardrailEventsAccess — dynamodb:PutItem on the guardrail events
#      table (chat agents only, conditional). Chat agents persist guardrail
#      intervention events for admin dashboard visibility.
#
# Run after deploying agents: task deploy:iam
#
# Uses inline policies (put-role-policy) so they aren't overwritten by
# agentcore deploy. Each policy has a stable name so re-runs are idempotent.

set -e

source "$(dirname "$0")/common.sh"

echo "=================================="
echo "Grant Agent Permissions"
echo "=================================="
echo ""

init_deployment

# ── Resolve resources from SSM ────────────────────────────────────
TABLE_NAME=$(ssm_get "dynamodb-table" 2>/dev/null || echo "${PROJECT_NAME}-projects-${ENVIRONMENT}")
TABLE_ARN="arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/${TABLE_NAME}"

SHARED_MEMORY_ARN=$(ssm_get "memory/shared_memory_arn" 2>/dev/null || echo "")

# Knowledge Base IDs — the review + chat runtimes call bedrock:Retrieve via the
# search_document (Document KB) and lookup_standard (Standards KB) tools.
DOCUMENT_KB_ID=$(ssm_get "kb/document_kb_id" 2>/dev/null || echo "")
STANDARDS_KB_ID=$(ssm_get "kb/standards_kb_id" 2>/dev/null || echo "")
KB_RESOURCES=()
[ -n "$DOCUMENT_KB_ID" ] && KB_RESOURCES+=("arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:knowledge-base/${DOCUMENT_KB_ID}")
[ -n "$STANDARDS_KB_ID" ] && KB_RESOURCES+=("arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:knowledge-base/${STANDARDS_KB_ID}")

# Guardrail — optional, only exists after the guardrails Terraform module is applied.
GUARDRAIL_ID=$(ssm_get "guardrail/id" 2>/dev/null || echo "")
if [ -n "$GUARDRAIL_ID" ]; then
    GUARDRAIL_ARN="arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:guardrail/${GUARDRAIL_ID}"
fi

# Guardrail events table — optional, only exists after the data module creates it.
GUARDRAIL_EVENTS_TABLE=$(ssm_get "guardrail-events-table" 2>/dev/null || echo "")
if [ -n "$GUARDRAIL_EVENTS_TABLE" ]; then
    GUARDRAIL_EVENTS_TABLE_ARN="arn:aws:dynamodb:${AWS_REGION}:${AWS_ACCOUNT_ID}:table/${GUARDRAIL_EVENTS_TABLE}"
fi

echo "Projects table: ${TABLE_NAME}"
echo "Table ARN: ${TABLE_ARN}"
if [ -n "$SHARED_MEMORY_ARN" ]; then
    echo "Shared Memory ARN: ${SHARED_MEMORY_ARN}"
else
    echo "Shared Memory: not configured (skipping SharedMemoryAccess)"
fi
if [ ${#KB_RESOURCES[@]} -gt 0 ]; then
    echo "Knowledge Bases: ${KB_RESOURCES[*]}"
else
    echo "Knowledge Bases: not configured (skipping KnowledgeBaseAccess)"
fi
if [ -n "$GUARDRAIL_ID" ]; then
    echo "Guardrail ARN: ${GUARDRAIL_ARN}"
else
    echo "Guardrail: not configured (skipping GuardrailAccess)"
fi
if [ -n "$GUARDRAIL_EVENTS_TABLE" ]; then
    echo "Guardrail events table: ${GUARDRAIL_EVENTS_TABLE}"
else
    echo "Guardrail events table: not configured (skipping GuardrailEventsAccess)"
fi
echo ""

# ── Discover all agents from agent.yaml files ─────────────────────
ALL_AGENTS=()
CHAT_AGENTS=()
while IFS= read -r line; do
    name=$(echo "$line" | cut -d'|' -f1)
    role=$(echo "$line" | cut -d'|' -f2)
    ALL_AGENTS+=("$name")
    if [ "$role" = "chat" ]; then
        CHAT_AGENTS+=("$name")
    fi
done < <(python3 -c "
import yaml, glob
for f in sorted(glob.glob('agents/*/agent.yaml')):
    with open(f) as fh:
        cfg = yaml.safe_load(fh)
    print(f'{cfg[\"name\"]}|{cfg[\"role\"]}')
")

echo "Discovered ${#ALL_AGENTS[@]} agents (${#CHAT_AGENTS[@]} chat)"
echo ""

# ── Helper: get execution role name from agentcore status ─────────
get_role_name() {
    local agent_key="$1"
    local raw_output
    local role_name

    # Capture agentcore status output. The agentcore CLI may emit Python
    # warnings (e.g., urllib3/requests version mismatches) to stdout before
    # the JSON. We extract only the JSON object and parse it.
    raw_output=$(agentcore status --agent "${agent_key}" --verbose 2>/dev/null) || {
        echo "  ❌ agentcore status failed for ${agent_key}" >&2
        return 1
    }

    role_name=$(echo "$raw_output" | python3 -c "
import sys, json

# Skip non-JSON lines (warnings, blank lines) and find the JSON object
lines = sys.stdin.read()
json_start = lines.find('{')
if json_start == -1:
    sys.exit(1)
# strict=False tolerates unescaped control characters in string values,
# which the agentcore CLI sometimes emits in its JSON output.
d = json.loads(lines[json_start:], strict=False)
role_arn = d.get('config', {}).get('execution_role', '')
if role_arn:
    print(role_arn.split('/')[-1])
else:
    sys.exit(1)
") || {
        echo "  ❌ Could not parse execution role for ${agent_key}" >&2
        echo "     Raw output: ${raw_output:0:200}" >&2
        return 1
    }

    echo "$role_name"
}

# ── Policy documents ──────────────────────────────────────────────
REGISTRY_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AgentRegistryRead",
      "Effect": "Allow",
      "Action": "dynamodb:GetItem",
      "Resource": "${TABLE_ARN}"
    }
  ]
}
EOF
)

if [ -n "$SHARED_MEMORY_ARN" ]; then
MEMORY_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SharedSemanticMemoryAccess",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:RetrieveMemoryRecords",
      "Resource": "${SHARED_MEMORY_ARN}"
    }
  ]
}
EOF
)
fi

if [ ${#KB_RESOURCES[@]} -gt 0 ]; then
KB_RESOURCE_JSON=$(printf '"%s",' "${KB_RESOURCES[@]}")
KB_RESOURCE_JSON="[${KB_RESOURCE_JSON%,}]"
KB_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": "bedrock:Retrieve",
      "Resource": ${KB_RESOURCE_JSON}
    }
  ]
}
EOF
)
fi

if [ -n "$GUARDRAIL_ID" ]; then
GUARDRAIL_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockGuardrailAccess",
      "Effect": "Allow",
      "Action": "bedrock:ApplyGuardrail",
      "Resource": "${GUARDRAIL_ARN}"
    }
  ]
}
EOF
)
fi

if [ -n "$GUARDRAIL_EVENTS_TABLE" ]; then
GUARDRAIL_EVENTS_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "GuardrailEventsWrite",
      "Effect": "Allow",
      "Action": "dynamodb:PutItem",
      "Resource": "${GUARDRAIL_EVENTS_TABLE_ARN}"
    }
  ]
}
EOF
)
fi

# ── Grant RegistryAccess to all agents ────────────────────────────
echo "Granting RegistryAccess (DynamoDB) to all agents..."
FAILED=()
SEEN_ROLES=()
RESOLVED_ROLES=()  # "agent_key|role_name" pairs, reused by later loops

for agent_key in "${ALL_AGENTS[@]}"; do
    # get_role_name may fail (agent not deployed, CLI issues) — capture
    # the error but don't let set -e abort the entire script. The function
    # prints diagnostics to stderr on failure.
    ROLE_NAME=""
    ROLE_NAME=$(get_role_name "$agent_key") || true
    if [ -z "$ROLE_NAME" ]; then
        echo "  ⚠️  Skipping ${agent_key} — could not resolve execution role"
        echo "     Deploy this agent first: task deploy:agent -- ${agent_key}"
        FAILED+=("$agent_key")
        continue
    fi

    # Cache for reuse in SharedMemoryAccess and GuardrailAccess loops.
    RESOLVED_ROLES+=("${agent_key}|${ROLE_NAME}")

    # Skip if we already granted this role (agents may share a role).
    # Quoted RHS is intentional: a literal space-delimited membership test,
    # not a regex match.
    # shellcheck disable=SC2076
    if [[ " ${SEEN_ROLES[*]} " =~ " ${ROLE_NAME} " ]]; then
        echo "  ✓ ${agent_key} (${ROLE_NAME}) — already granted"
        continue
    fi
    SEEN_ROLES+=("$ROLE_NAME")

    aws iam put-role-policy \
        --role-name "${ROLE_NAME}" \
        --policy-name "RegistryAccess" \
        --policy-document "${REGISTRY_POLICY}" \
        --region "${AWS_REGION}"

    echo "  ✓ ${agent_key} (${ROLE_NAME})"
done
echo ""

# ── Grant SharedMemoryAccess to all agents ────────────────────────
# Review agents read prior findings via get_prior_findings; chat agents read
# findings to answer questions. Both need RetrieveMemoryRecords.
if [ -n "$SHARED_MEMORY_ARN" ]; then
    echo "Granting SharedMemoryAccess (RetrieveMemoryRecords) to all agents..."
    SEEN_MEMORY_ROLES=()
    for entry in "${RESOLVED_ROLES[@]}"; do
        IFS='|' read -r agent_key ROLE_NAME <<< "$entry"

        # shellcheck disable=SC2076  # intentional literal substring match
        if [[ " ${SEEN_MEMORY_ROLES[*]} " =~ " ${ROLE_NAME} " ]]; then
            echo "  ✓ ${agent_key} (${ROLE_NAME}) — already granted"
            continue
        fi
        SEEN_MEMORY_ROLES+=("$ROLE_NAME")

        aws iam put-role-policy \
            --role-name "${ROLE_NAME}" \
            --policy-name "SharedMemoryAccess" \
            --policy-document "${MEMORY_POLICY}" \
            --region "${AWS_REGION}"

        echo "  ✓ ${agent_key} (${ROLE_NAME})"
    done
    echo ""
fi

# ── Grant KnowledgeBaseAccess to all agents ───────────────────────
# Review agents call bedrock:Retrieve via search_document (Document KB) and
# lookup_standard (Standards KB); chat agents call the same tools.
if [ ${#KB_RESOURCES[@]} -gt 0 ]; then
    echo "Granting KnowledgeBaseAccess (bedrock:Retrieve) to all agents..."
    SEEN_KB_ROLES=()
    for entry in "${RESOLVED_ROLES[@]}"; do
        IFS='|' read -r agent_key ROLE_NAME <<< "$entry"

        # shellcheck disable=SC2076  # intentional literal substring match
        if [[ " ${SEEN_KB_ROLES[*]} " =~ " ${ROLE_NAME} " ]]; then
            echo "  ✓ ${agent_key} (${ROLE_NAME}) — already granted"
            continue
        fi
        SEEN_KB_ROLES+=("$ROLE_NAME")

        aws iam put-role-policy \
            --role-name "${ROLE_NAME}" \
            --policy-name "KnowledgeBaseAccess" \
            --policy-document "${KB_POLICY}" \
            --region "${AWS_REGION}"

        echo "  ✓ ${agent_key} (${ROLE_NAME})"
    done
    echo ""
fi

# ── Grant GuardrailAccess to all agents ───────────────────────────
if [ -n "$GUARDRAIL_ID" ]; then
    echo "Granting GuardrailAccess (bedrock:ApplyGuardrail) to all agents..."
    SEEN_GUARDRAIL_ROLES=()
    for entry in "${RESOLVED_ROLES[@]}"; do
        IFS='|' read -r agent_key ROLE_NAME <<< "$entry"

        # Skip if we already granted this role (agents may share a role).
        # shellcheck disable=SC2076  # intentional literal substring match
        if [[ " ${SEEN_GUARDRAIL_ROLES[*]} " =~ " ${ROLE_NAME} " ]]; then
            echo "  ✓ ${agent_key} (${ROLE_NAME}) — already granted"
            continue
        fi
        SEEN_GUARDRAIL_ROLES+=("$ROLE_NAME")

        aws iam put-role-policy \
            --role-name "${ROLE_NAME}" \
            --policy-name "GuardrailAccess" \
            --policy-document "${GUARDRAIL_POLICY}" \
            --region "${AWS_REGION}"

        echo "  ✓ ${agent_key} (${ROLE_NAME})"
    done
    echo ""
fi

# ── Grant GuardrailEventsAccess to chat agents ────────────────────
if [ -n "$GUARDRAIL_EVENTS_TABLE" ] && [ ${#CHAT_AGENTS[@]} -gt 0 ]; then
    echo "Granting GuardrailEventsAccess (dynamodb:PutItem) to chat agents..."
    for agent_key in "${CHAT_AGENTS[@]}"; do
        ROLE_NAME=""
        for entry in "${RESOLVED_ROLES[@]}"; do
            IFS='|' read -r cached_key cached_role <<< "$entry"
            if [ "$cached_key" = "$agent_key" ]; then
                ROLE_NAME="$cached_role"
                break
            fi
        done
        if [ -z "$ROLE_NAME" ]; then
            continue
        fi

        aws iam put-role-policy \
            --role-name "${ROLE_NAME}" \
            --policy-name "GuardrailEventsAccess" \
            --policy-document "${GUARDRAIL_EVENTS_POLICY}" \
            --region "${AWS_REGION}"

        echo "  ✓ ${agent_key} (${ROLE_NAME})"
    done
    echo ""
fi

# ── Summary ───────────────────────────────────────────────────────
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "=================================="
    echo "Agent permissions granted ✓"
    echo "=================================="
else
    echo "=================================="
    echo "Completed with ${#FAILED[@]} skipped: ${FAILED[*]}"
    echo "=================================="
fi
