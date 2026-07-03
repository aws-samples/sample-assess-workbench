#!/usr/bin/env bash
# Delete the shared semantic memory for this project/environment.
#
# Owns ONLY the standalone shared semantic memory. Per-agent chat memories are
# bound to their agent runtime and are deleted by `agentcore destroy`
# (destroy_agents.sh) — deleting them here too caused a double-delete
# (ResourceNotFound on the already-gone memory). Self-guarding: sources
# with-env.sh, which asserts the live AWS account matches the resolved
# environment. Invoked by `task destroy:memory`.
#
# pipefail (not `set -e`): a failed delete warns and continues rather than abort.

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh
# shellcheck source=scripts/common.sh
source scripts/common.sh

: "${PROJECT_NAME:?destroy_memory: PROJECT_NAME must be set}"
: "${ENVIRONMENT:?destroy_memory: ENVIRONMENT must be set}"
: "${AWS_REGION:?destroy_memory: AWS_REGION must be set}"

echo "Cleaning up shared memory..."
echo ""

DELETED=0

# ── Helper: delete a single memory and wait for completion ──
delete_and_wait() {
  local memory_id="$1"
  local label="$2"

  echo "Deleting ${label} (${memory_id})..."
  local err
  if ! err=$(aws bedrock-agentcore-control delete-memory \
    --memory-id "$memory_id" \
    --client-token "delete-${memory_id}-$(date +%s)" \
    --region "${AWS_REGION}" 2>&1); then
    # A missing memory is already gone — treat as success (idempotent), not an
    # error. Any other failure is real and propagates as a warning.
    if printf '%s' "$err" | grep -q 'ResourceNotFoundException'; then
      echo "  ✓ Already deleted"
      return 0
    fi
    echo "  ⚠️  Could not initiate deletion of ${memory_id}: ${err}"
    return 1
  fi

  # Wait for this memory to be fully deleted
  local timeout=120
  local elapsed=0
  while [ $elapsed -lt $timeout ]; do
    local remaining
    remaining=$(aws bedrock-agentcore-control list-memories \
      --region "${AWS_REGION}" \
      --query "memories[?id=='${memory_id}'].id | [0]" \
      --output text 2>/dev/null)
    if [ -z "$remaining" ] || [ "$remaining" = "None" ]; then
      echo "  ✓ Deleted"
      DELETED=$((DELETED + 1))
      return 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
  echo "  ❌ Timeout waiting for ${memory_id}"
  return 1
}

# ── Shared memory ──
MEMORY_PREFIX="$(shared_memory_name)"
SHARED_IDS=$(aws bedrock-agentcore-control list-memories \
  --region "${AWS_REGION}" \
  --query "memories[?starts_with(id, '${MEMORY_PREFIX}')].id" \
  --output text 2>/dev/null)

if [ -n "$SHARED_IDS" ] && [ "$SHARED_IDS" != "None" ]; then
  for SHARED_ID in $SHARED_IDS; do
    delete_and_wait "$SHARED_ID" "shared memory"
  done
else
  echo "No shared memory found matching '${MEMORY_PREFIX}'"
fi
echo ""

if [ $DELETED -gt 0 ]; then
  echo "✓ ${DELETED} memory resource(s) deleted"
else
  echo "Nothing to delete"
fi
