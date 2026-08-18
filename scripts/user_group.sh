#!/usr/bin/env bash
# Change a user's Cognito group: remove from all current groups, add to the new.
#
# Usage: bash scripts/user_group.sh "<email> <group>"  (Taskfile passes CLI_ARGS
# as a single argument). Self-guarding: sources with-env.sh, which asserts the
# live AWS account matches the resolved environment. Invoked by `task user:group`.
#
# pipefail (not `set -e`): matches the original task block; explicit checks below
# handle the failures that matter (bad usage, missing pool, invalid group).

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

ARGS="${1:-}"
EMAIL=$(echo "$ARGS" | awk '{print $1}')
GROUP=$(echo "$ARGS" | awk '{print $2}')

if [ -z "$EMAIL" ] || [ -z "$GROUP" ]; then
  echo "Usage: task user:group -- <email> <group>"
  echo ""
  echo "Available groups: admins, users, viewers"
  exit 1
fi

# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh

: "${ENVIRONMENT:?user_group: ENVIRONMENT must be set}"
: "${AWS_REGION:?user_group: AWS_REGION must be set}"

export TF_DATA_DIR=".terraform/${ENVIRONMENT}"
REGION="${AWS_REGION}"

USER_POOL_ID=$(terraform -chdir=terraform output -raw cognito_user_pool_id 2>/dev/null || true)
if [ -z "$USER_POOL_ID" ]; then
  echo "❌ Could not read Cognito User Pool ID. Run 'task deploy:infra' first."
  exit 1
fi

# Validate group exists
VALID_GROUPS=$(aws cognito-idp list-groups \
  --user-pool-id "$USER_POOL_ID" \
  --region "$REGION" \
  --query 'Groups[].GroupName' --output text)
if ! echo "$VALID_GROUPS" | grep -qw "$GROUP"; then
  echo "❌ Invalid group: $GROUP"
  echo "   Available: $VALID_GROUPS"
  exit 1
fi

# Remove from all current groups
CURRENT=$(aws cognito-idp admin-list-groups-for-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --region "$REGION" \
  --query 'Groups[].GroupName' --output text 2>/dev/null)

for g in $CURRENT; do
  aws cognito-idp admin-remove-user-from-group \
    --user-pool-id "$USER_POOL_ID" \
    --username "$EMAIL" \
    --group-name "$g" \
    --region "$REGION"
done

# Add to new group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username "$EMAIL" \
  --group-name "$GROUP" \
  --region "$REGION"

echo "✓ $EMAIL → $GROUP"
if [ -n "$CURRENT" ]; then
  echo "  (removed from: $CURRENT)"
fi
