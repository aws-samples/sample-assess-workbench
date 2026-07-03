#!/bin/bash
# Deploy shared memory resource to AgentCore.
# Uses AWS CLI (bedrock-agentcore-control) with --query (JMESPath) — no jq needed.

set -e

source "$(dirname "$0")/common.sh"

echo "=================================="
echo "Deploy Shared Memory Resource"
echo "=================================="
echo ""

init_deployment

MEMORY_NAME="$(shared_memory_name)"

echo "Memory: ${MEMORY_NAME}"
echo "Region: ${AWS_REGION}"
echo ""

# ── Find existing memory by name prefix ──────────────────────────
echo "Checking for existing memory..."
MEMORY_ID=$(aws bedrock-agentcore-control list-memories \
  --region "${AWS_REGION}" \
  --query "memories[?starts_with(id, '${MEMORY_NAME}')].id | [0]" \
  --output text 2>/dev/null)

# --output text returns "None" for null results
if [ -n "$MEMORY_ID" ] && [ "$MEMORY_ID" != "None" ]; then
  MEMORY_ARN=$(aws bedrock-agentcore-control get-memory \
    --memory-id "${MEMORY_ID}" \
    --region "${AWS_REGION}" \
    --query 'memory.arn' --output text)
  MEMORY_STATUS=$(aws bedrock-agentcore-control get-memory \
    --memory-id "${MEMORY_ID}" \
    --region "${AWS_REGION}" \
    --query 'memory.status' --output text)

  echo "  Found: ${MEMORY_ID} (${MEMORY_STATUS})"
  echo "  ARN:   ${MEMORY_ARN}"
  echo ""

  if [ "$MEMORY_STATUS" != "ACTIVE" ]; then
    echo "  ❌ Memory is ${MEMORY_STATUS}, not ACTIVE."
    echo "     Delete it first: task destroy:memory"
    exit 1
  fi

  echo "Using existing memory resource."
else
  # ── Create new memory ────────────────────────────────────────────
  echo "Creating ${MEMORY_NAME}..."
  MEMORY_ID=$(aws bedrock-agentcore-control create-memory \
    --name "${MEMORY_NAME}" \
    --description "Shared semantic memory for all review findings and conversations" \
    --event-expiry-duration 90 \
    --memory-strategies '[{"semanticMemoryStrategy":{"name":"Findings"}}]' \
    --client-token "${MEMORY_NAME}-$(date +%s)" \
    --region "${AWS_REGION}" \
    --query 'memory.id' --output text)
  echo "  Memory ID: ${MEMORY_ID}"

  # ── Wait for ACTIVE ──────────────────────────────────────────────
  echo "Waiting for memory to become ACTIVE..."
  TIMEOUT=300
  ELAPSED=0
  while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(aws bedrock-agentcore-control get-memory \
      --memory-id "${MEMORY_ID}" \
      --region "${AWS_REGION}" \
      --query 'memory.status' --output text 2>/dev/null)

    if [ "$STATUS" = "ACTIVE" ]; then
      break
    elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "DELETE_FAILED" ]; then
      echo "  ❌ Memory entered ${STATUS} state"
      exit 1
    fi

    echo "  Waiting... (${STATUS}, ${ELAPSED}s)"
    sleep 5
    ELAPSED=$((ELAPSED + 5))
  done

  if [ "$STATUS" != "ACTIVE" ]; then
    echo "  ❌ Timeout after ${TIMEOUT}s"
    exit 1
  fi

  MEMORY_ARN=$(aws bedrock-agentcore-control get-memory \
    --memory-id "${MEMORY_ID}" \
    --region "${AWS_REGION}" \
    --query 'memory.arn' --output text)

  echo "✓ Memory active"
  echo "  ID:  ${MEMORY_ID}"
  echo "  ARN: ${MEMORY_ARN}"
  echo ""
fi

# ── Store ARN in SSM ───────────────────────────────────────────────
echo "Storing memory ARN in SSM..."
ssm_put "memory/shared_memory_arn" "${MEMORY_ARN}" "Shared semantic memory ARN"
echo ""
echo "================================"
echo "Deployment successful ✓"
echo "================================"
