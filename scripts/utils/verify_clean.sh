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

# ── Lambda functions ──────────────────────────────────────────────
# Terraform-managed. Normally gone after `task destroy`, but they orphan if the
# state is lost mid-teardown, so verify them directly as a backstop.
echo "── Lambda functions ──"
if fns="$(query "lambda list-functions" \
    aws lambda list-functions --region "$REGION" \
    --query "Functions[].FunctionName" --output text)"; then
    found=0
    for fn in $fns; do
        case "$fn" in
            "${PROJECT}-"*"-${ENV}") record "Lambda function: ${fn}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no Lambda functions matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── IAM roles ─────────────────────────────────────────────────────
echo "── IAM roles ──"
if roles="$(query "iam list-roles" \
    aws iam list-roles --query "Roles[].RoleName" --output text)"; then
    found=0
    for r in $roles; do
        case "$r" in
            "${PROJECT}-"*"-${ENV}") record "IAM role: ${r}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no IAM roles matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── API Gateway v2 APIs ───────────────────────────────────────────
echo "── API Gateway v2 ──"
if apis="$(query "apigatewayv2 get-apis" \
    aws apigatewayv2 get-apis --region "$REGION" \
    --query "Items[].Name" --output text)"; then
    found=0
    for a in $apis; do
        case "$a" in
            "${PROJECT}-"*"-${ENV}") record "API Gateway v2 API: ${a}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no API Gateway v2 APIs matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── DynamoDB tables ───────────────────────────────────────────────
# The Terraform lock table (${PROJECT}-terraform-locks) does not match
# ${PROJECT}-*-${ENV}, so it is left to the backend section below.
echo "── DynamoDB tables ──"
if tables="$(query "dynamodb list-tables" \
    aws dynamodb list-tables --region "$REGION" \
    --query "TableNames[]" --output text)"; then
    found=0
    for t in $tables; do
        case "$t" in
            "${PROJECT}-"*"-${ENV}") record "DynamoDB table: ${t}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no DynamoDB tables matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── Cognito user pools ────────────────────────────────────────────
echo "── Cognito user pools ──"
if pools="$(query "cognito-idp list-user-pools" \
    aws cognito-idp list-user-pools --max-results 60 --region "$REGION" \
    --query "UserPools[].Name" --output text)"; then
    found=0
    for p in $pools; do
        case "$p" in
            "${PROJECT}-"*"-${ENV}") record "Cognito user pool: ${p}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no Cognito user pools matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── Step Functions state machines ─────────────────────────────────
echo "── Step Functions ──"
if sms="$(query "stepfunctions list-state-machines" \
    aws stepfunctions list-state-machines --region "$REGION" \
    --query "stateMachines[].name" --output text)"; then
    found=0
    for sm in $sms; do
        case "$sm" in
            "${PROJECT}-"*"-${ENV}") record "Step Functions state machine: ${sm}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no Step Functions state machines matching ${PROJECT}-*-${ENV}"
fi
echo ""

# ── Bedrock guardrails ────────────────────────────────────────────
# Named ${PROJECT}-${ENV}-guardrail, so match project prefix + env anywhere
# after it rather than the ${PROJECT}-*-${ENV} suffix glob used elsewhere.
echo "── Bedrock guardrails ──"
if guardrails="$(query "bedrock list-guardrails" \
    aws bedrock list-guardrails --region "$REGION" \
    --query "guardrails[].name" --output text)"; then
    found=0
    for g in $guardrails; do
        case "$g" in
            "${PROJECT}-"*"${ENV}"*) record "Bedrock guardrail: ${g}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no Bedrock guardrails matching ${PROJECT}-*${ENV}*"
fi
echo ""

# ── CloudWatch Logs delivery (KB application logs) ────────────────
# Named ${PROJECT}-standards-kb-${ENV}-app-logs (env is not the suffix).
echo "── CloudWatch Logs delivery ──"
if dsrc="$(query "logs describe-delivery-sources" \
    aws logs describe-delivery-sources --region "$REGION" \
    --query "deliverySources[].name" --output text)"; then
    found=0
    for d in $dsrc; do
        case "$d" in
            "${PROJECT}-"*"${ENV}"*) record "CW Logs delivery source: ${d}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no CW Logs delivery sources matching ${PROJECT}-*${ENV}*"
fi
if ddst="$(query "logs describe-delivery-destinations" \
    aws logs describe-delivery-destinations --region "$REGION" \
    --query "deliveryDestinations[].name" --output text)"; then
    found=0
    for d in $ddst; do
        case "$d" in
            "${PROJECT}-"*"${ENV}"*) record "CW Logs delivery destination: ${d}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no CW Logs delivery destinations matching ${PROJECT}-*${ENV}*"
fi
echo ""

# ── CloudFront / edge (global; WAF is CLOUDFRONT scope in us-east-1) ──
# The edge module (WAF web ACL, CloudFront distribution + functions + response-
# headers policies + OAC, and the WAF log group) lives outside $REGION. These
# are Terraform-managed and gone after `task destroy`, but a lost-state teardown
# orphans them where the single-region checks above cannot see them.
echo "── CloudFront / edge (us-east-1) ──"
# Distributions have no Name; match the edge module's comment "<project> frontend (<env>)".
if dists="$(query "cloudfront list-distributions" \
    aws cloudfront list-distributions \
    --query "DistributionList.Items[].Comment" --output text)"; then
    found=0
    while IFS= read -r c; do
        [ -z "$c" ] && continue
        case "$c" in
            *"${PROJECT} frontend (${ENV})"*) record "CloudFront distribution: ${c}"; found=1 ;;
        esac
    done <<EOF
$dists
EOF
    [ "$found" -eq 0 ] && ok "no CloudFront distribution matching '${PROJECT} frontend (${ENV})'"
fi

if fns="$(query "cloudfront list-functions" \
    aws cloudfront list-functions --query "FunctionList.Items[].Name" --output text)"; then
    found=0
    for fn in $fns; do
        case "$fn" in
            "${PROJECT}-"*"-${ENV}") record "CloudFront function: ${fn}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no CloudFront functions matching ${PROJECT}-*-${ENV}"
fi

if rhps="$(query "cloudfront list-response-headers-policies" \
    aws cloudfront list-response-headers-policies \
    --query "ResponseHeadersPolicyList.Items[].ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name" \
    --output text)"; then
    found=0
    for p in $rhps; do
        case "$p" in
            "${PROJECT}-"*"-${ENV}") record "CloudFront response-headers policy: ${p}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no CloudFront response-headers policies matching ${PROJECT}-*-${ENV}"
fi

if oacs="$(query "cloudfront list-origin-access-controls" \
    aws cloudfront list-origin-access-controls \
    --query "OriginAccessControlList.Items[].Name" --output text)"; then
    found=0
    for o in $oacs; do
        case "$o" in
            "${PROJECT}-"*"-${ENV}") record "CloudFront OAC: ${o}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no CloudFront OAC matching ${PROJECT}-*-${ENV}"
fi

# list-origin-request-policies returns AWS-managed policies too; the name
# prefix filter excludes them.
if orps="$(query "cloudfront list-origin-request-policies" \
    aws cloudfront list-origin-request-policies \
    --query "OriginRequestPolicyList.Items[].OriginRequestPolicy.OriginRequestPolicyConfig.Name" \
    --output text)"; then
    found=0
    for orp in $orps; do
        case "$orp" in
            "${PROJECT}-"*"-${ENV}") record "CloudFront origin request policy: ${orp}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no CloudFront origin request policies matching ${PROJECT}-*-${ENV}"
fi

if acls="$(query "wafv2 list-web-acls (CLOUDFRONT)" \
    aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 \
    --query "WebACLs[].Name" --output text)"; then
    found=0
    for a in $acls; do
        case "$a" in
            "${PROJECT}-"*"-${ENV}") record "WAF web ACL: ${a}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no WAF web ACLs matching ${PROJECT}-*-${ENV}"
fi

if waf_lgs="$(query "logs describe-log-groups (us-east-1 WAF)" \
    aws logs describe-log-groups --region us-east-1 \
    --log-group-name-prefix "aws-waf-logs-${PROJECT}-" \
    --query "logGroups[].logGroupName" --output text)"; then
    found=0
    for lg in $waf_lgs; do
        case "$lg" in
            *"${ENV}") record "WAF log group: ${lg}"; found=1 ;;
        esac
    done
    [ "$found" -eq 0 ] && ok "no WAF log groups matching aws-waf-logs-${PROJECT}-*${ENV}"
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
