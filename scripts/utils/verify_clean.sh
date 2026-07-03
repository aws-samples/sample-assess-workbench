#!/bin/bash
# Verify an environment is fully torn down.
#
# Queries the live account for any resource belonging to this project +
# environment and exits non-zero, listing every survivor, if anything remains.
# Read-only: it never deletes. Safe to run anytime — after `task destroy`, after
# Isengard Nuke, or on its own to audit an account.
#
# Keys off the resolved AWS_REGION / ENVIRONMENT / PROJECT_NAME (from .env).
#
# A failed query is reported as a failure, never silently treated as "clean":
# the whole point is to refuse to claim an account is empty when we could not
# actually check.
#
# Usage:
#   task verify:clean                      # resource sweep (backend preserved)
#   task verify:clean -- --include-backend # also assert the Terraform backend is gone
#   bash scripts/utils/verify_clean.sh [--include-backend]

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}" || exit 1

source "${REPO_ROOT}/scripts/common.sh"
load_env
require_env

INCLUDE_BACKEND=false
[ "${1:-}" = "--include-backend" ] && INCLUDE_BACKEND=true

REGION="${AWS_REGION}"
PROJECT="${PROJECT_NAME}"
ENV="${ENVIRONMENT}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo 'unknown')"

echo "=================================="
echo "Verify Clean Teardown"
echo "=================================="
echo "  Project:     ${PROJECT}"
echo "  Environment: ${ENV}"
echo "  Region:      ${REGION}"
echo "  Account:     ${ACCOUNT}"
echo "  Backend:     $([ "$INCLUDE_BACKEND" = true ] && echo 'checked (expect gone)' || echo 'skipped (preserved by task destroy)')"
echo ""

SURVIVORS=()
record() { SURVIVORS+=("$1"); echo "  ✗ $1"; }
ok()     { echo "  ✓ $1"; }

# Run an AWS query; echo stdout on success. On failure, record a survivor (so
# an unverifiable check fails the run) and echo nothing.
# Usage: out=$(query "<label>" aws <args...>)
query() {
    local label="$1"; shift
    local out err
    err="$(mktemp)"
    if out="$("$@" 2>"$err")"; then
        rm -f "$err"
        printf '%s' "$out"
        return 0
    fi
    record "check could not run: ${label} — $(tr '\n' ' ' <"$err" | sed 's/  */ /g')"
    rm -f "$err"
    return 1
}

# ── S3 Vectors buckets ────────────────────────────────────────────
# Match against raw JSON so the check survives field-name drift in this new API.
echo "── S3 Vectors ──"
if vec_json="$(query "s3vectors list-vector-buckets" \
    aws s3vectors list-vector-buckets --region "$REGION" --output json)"; then
    for name in "${PROJECT}-document-kb-${ENV}" "${PROJECT}-standards-kb-${ENV}"; do
        if printf '%s' "$vec_json" | grep -q "\"${name}\""; then
            record "S3 Vectors bucket: ${name}"
        else
            ok "no S3 Vectors bucket: ${name}"
        fi
    done
fi
echo ""

# ── Bedrock Knowledge Bases ───────────────────────────────────────
echo "── Bedrock Knowledge Bases ──"
if kb_names="$(query "bedrock-agent list-knowledge-bases" \
    aws bedrock-agent list-knowledge-bases --region "$REGION" \
    --query "knowledgeBaseSummaries[].name" --output text)"; then
    found=0
    for kb in $kb_names; do
        case "$kb" in
            "${PROJECT}-"*"-${ENV}") record "Knowledge Base: ${kb}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no Knowledge Bases matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── AgentCore runtimes ────────────────────────────────────────────
# Runtime names are NOT project/env-namespaced (they are the agents/*/agent.yaml
# names), so match the live runtimes against the names this repo would deploy.
echo "── AgentCore runtimes ──"
expected_agents="$(find agents -name agent.yaml -type f 2>/dev/null \
    | sort \
    | xargs -I{} python3 -c "import yaml,sys; print(yaml.safe_load(open('{}'))['name'])" 2>/dev/null)"
if [ -z "$expected_agents" ]; then
    record "could not read expected agent names from agents/*/agent.yaml"
elif runtime_names="$(query "bedrock-agentcore-control list-agent-runtimes" \
    aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[].agentRuntimeName" --output text)"; then
    found=0
    for rt in $runtime_names; do
        if printf '%s\n' "$expected_agents" | grep -qx "$rt"; then
            record "AgentCore runtime: ${rt}"; found=1
        fi
    done
    [ "$found" -eq 0 ] && ok "no AgentCore runtimes matching this project's agents"
fi
echo ""

# ── AgentCore runtime log groups ──────────────────────────────────
# The runtime service auto-creates /aws/bedrock-agentcore/runtimes/<id>-<endpoint>
# per runtime and `agentcore destroy` leaves them behind. Match the same way as
# runtimes: by expected agent name plus a trailing hyphen (so 'architect-' does
# not catch 'architect_chat-').
echo "── AgentCore runtime log groups ──"
if [ -z "$expected_agents" ]; then
    record "could not read expected agent names from agents/*/agent.yaml"
elif rt_log_groups="$(query "logs describe-log-groups (agentcore runtimes)" \
    aws logs describe-log-groups \
    --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/" \
    --query "logGroups[].logGroupName" --output text --region "$REGION")"; then
    found=0
    for lg in $rt_log_groups; do
        rest=${lg#/aws/bedrock-agentcore/runtimes/}
        for agent in $expected_agents; do
            case "$rest" in
                "${agent}-"*) record "AgentCore runtime log group: ${lg}"; found=1; break ;;
            esac
        done
    done
    [ "$found" -eq 0 ] && ok "no AgentCore runtime log groups matching this project's agents"
fi
echo ""

# ── AgentCore memories ────────────────────────────────────────────
echo "── AgentCore memories ──"
mem_name="$(shared_memory_name)"
if mem_ids="$(query "bedrock-agentcore-control list-memories" \
    aws bedrock-agentcore-control list-memories --region "$REGION" \
    --query "memories[?starts_with(id, '${mem_name}')].id" --output text)"; then
    if [ -n "$mem_ids" ] && [ "$mem_ids" != "None" ]; then
        for m in $mem_ids; do record "AgentCore memory: ${m}"; done
    else
        ok "no shared memory matching ${mem_name}"
    fi
fi
echo ""

# ── S3 buckets ────────────────────────────────────────────────────
echo "── S3 buckets ──"
if buckets="$(query "s3api list-buckets" \
    aws s3api list-buckets --query "Buckets[].Name" --output text)"; then
    found=0
    for b in $buckets; do
        case "$b" in
            "${PROJECT}-"*"-${ENV}"|"${PROJECT}-"*"-${ENV}-"*)
                record "S3 bucket: ${b}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no S3 buckets matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── SSM parameters ────────────────────────────────────────────────
echo "── SSM parameters ──"
if params="$(query "ssm get-parameters-by-path" \
    aws ssm get-parameters-by-path --path "/${PROJECT}/${ENV}" --recursive \
    --query "Parameters[].Name" --output text --region "$REGION")"; then
    if [ -n "$params" ]; then
        n=$(printf '%s' "$params" | tr '\t' '\n' | grep -c .)
        record "SSM parameters under /${PROJECT}/${ENV} (${n})"
    else
        ok "no SSM parameters under /${PROJECT}/${ENV}"
    fi
fi
echo ""

# ── CloudWatch log groups ─────────────────────────────────────────
echo "── CloudWatch log groups ──"
if lgs="$(query "logs describe-log-groups" \
    aws logs describe-log-groups \
    --query "logGroups[?contains(logGroupName, '${PROJECT}')].logGroupName" \
    --output text --region "$REGION")"; then
    found=0
    for lg in $lgs; do
        case "$lg" in
            *"${ENV}"*) record "Log group: ${lg}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no log groups matching ${PROJECT}*${ENV}"
fi
echo ""

# ── Terraform backend (opt-in: expected gone only after Nuke) ─────
if [ "$INCLUDE_BACKEND" = true ]; then
    echo "── Terraform backend ──"
    state_bucket="${PROJECT}-terraform-state-${ACCOUNT}"
    if aws s3api head-bucket --bucket "$state_bucket" --region "$REGION" 2>/dev/null; then
        record "TF state bucket: ${state_bucket}"
    else
        ok "no TF state bucket: ${state_bucket}"
    fi

    lock_table="${PROJECT}-terraform-locks"
    if aws dynamodb describe-table --table-name "$lock_table" --region "$REGION" >/dev/null 2>&1; then
        record "TF lock table: ${lock_table}"
    else
        ok "no TF lock table: ${lock_table}"
    fi

    if alias="$(query "kms list-aliases" \
        aws kms list-aliases --region "$REGION" \
        --query "Aliases[?AliasName=='alias/terraform-state'].AliasName" --output text)"; then
        if [ -n "$alias" ] && [ "$alias" != "None" ]; then
            record "KMS alias: alias/terraform-state"
        else
            ok "no KMS alias: alias/terraform-state"
        fi
    fi
    echo ""
fi

# ── Verdict ───────────────────────────────────────────────────────
echo "=================================="
if [ "${#SURVIVORS[@]}" -eq 0 ]; then
    echo "✓ Clean — no ${PROJECT}/${ENV} resources found in ${REGION}."
    echo "=================================="
    exit 0
fi
echo "❌ ${#SURVIVORS[@]} survivor(s) / unverifiable check(s):"
for s in "${SURVIVORS[@]}"; do echo "   - $s"; done
echo "=================================="
exit 1
