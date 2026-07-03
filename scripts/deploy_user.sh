#!/usr/bin/env bash
# Create a Cognito user (interactive) with a permanent password and group.
#
# Prompts for email, password (offering a generated default), and group, then
# creates the user, sets a permanent password (no forced change on first login),
# and assigns the group. Self-guarding: sources with-env.sh, which asserts the
# live AWS account matches the resolved environment. Invoked by `task
# deploy:user` (which runs it interactively).
#
# pipefail (not `set -e`): matches the original task block; explicit checks below
# handle the failures that matter (missing user pool, empty email, bad group).

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh

: "${ENVIRONMENT:?deploy_user: ENVIRONMENT must be set}"
: "${AWS_REGION:?deploy_user: AWS_REGION must be set}"

export TF_DATA_DIR=".terraform/${ENVIRONMENT}"
REGION="${AWS_REGION}"

USER_POOL_ID=$(terraform -chdir=terraform output -raw cognito_user_pool_id 2>/dev/null || true)
if [ -z "$USER_POOL_ID" ]; then
  echo "❌ Could not read Cognito User Pool ID. Run 'task deploy:infra' first."
  exit 1
fi

echo "Creating Cognito user..."
echo "Environment: ${ENVIRONMENT}"
echo "User Pool: ${USER_POOL_ID}"
echo ""

# Generated fallback password (used when none is supplied, in either mode).
# Finite read (256 bytes) avoids SIGPIPE with pipefail enabled.
RAW="$(head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9!@#%')"
DEFAULT_PW="${RAW:0:12}!"

if [ -n "${USER_EMAIL:-}" ]; then
  # ── Non-interactive: inputs from the environment ──
  # USER_EMAIL required; USER_PASSWORD optional (generated if absent);
  # USER_GROUP optional (defaults to "users", validated against the pool).
  EMAIL="${USER_EMAIL}"
  PASSWORD="${USER_PASSWORD:-${DEFAULT_PW}}"
  GROUP_NAME="${USER_GROUP:-users}"

  if ! aws cognito-idp get-group \
      --user-pool-id "${USER_POOL_ID}" \
      --group-name "${GROUP_NAME}" \
      --region "${REGION}" > /dev/null 2>&1; then
    echo "❌ Group '${GROUP_NAME}' not found in user pool ${USER_POOL_ID} (set USER_GROUP)."
    exit 1
  fi
  echo "Non-interactive: creating ${EMAIL} in group ${GROUP_NAME}"
else
  # ── Email ──
  read -rp "Email address: " EMAIL
  if [ -z "$EMAIL" ]; then
    echo "❌ Email is required"
    exit 1
  fi

  # ── Password ──
  # Press Enter to use the generated default above.
  echo ""
  echo "Enter a password or press Enter to use a generated one."
  echo "  Requirements: 8+ chars, uppercase, lowercase, number, symbol"
  read -rp "Password [${DEFAULT_PW}]: " PASSWORD
  PASSWORD="${PASSWORD:-${DEFAULT_PW}}"

  # ── Group ──
  echo ""
  echo "Fetching groups from Cognito..."
  GROUPS_JSON=$(aws cognito-idp list-groups \
    --user-pool-id "${USER_POOL_ID}" \
    --region "${REGION}" \
    --query 'Groups[].{name:GroupName,desc:Description}' \
    --output json 2>/dev/null)

  GROUP_COUNT=$(echo "${GROUPS_JSON}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

  GROUP_NAME=""
  if [ "${GROUP_COUNT}" -gt 0 ]; then
    echo ""
    echo "Select group:"

    # Build the menu and find the default index
    DEFAULT_IDX=1
    for i in $(seq 0 $((GROUP_COUNT - 1))); do
      NAME=$(echo "${GROUPS_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin)[${i}]['name'])")
      DESC=$(echo "${GROUPS_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin)[${i}].get('desc','') or '')")
      NUM=$((i + 1))
      if [ -n "${DESC}" ]; then
        echo "  ${NUM}) ${NAME}  — ${DESC}"
      else
        echo "  ${NUM}) ${NAME}"
      fi
      # Default to the "users" group (not admins, not viewers)
      if echo "${NAME}" | grep -q "users"; then
        DEFAULT_IDX=${NUM}
      fi
    done

    echo ""
    read -rp "Group [${DEFAULT_IDX}]: " GROUP_CHOICE
    GROUP_CHOICE="${GROUP_CHOICE:-${DEFAULT_IDX}}"

    # Validate selection
    if ! echo "${GROUP_CHOICE}" | grep -qE '^[0-9]+$' || [ "${GROUP_CHOICE}" -lt 1 ] || [ "${GROUP_CHOICE}" -gt "${GROUP_COUNT}" ]; then
      echo "❌ Invalid selection: ${GROUP_CHOICE}"
      exit 1
    fi

    GROUP_NAME=$(echo "${GROUPS_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin)[$((GROUP_CHOICE - 1))]['name'])")
  fi
fi

# ── Create user ──
echo ""
echo "Creating user..."
aws cognito-idp admin-create-user \
  --user-pool-id "${USER_POOL_ID}" \
  --username "${EMAIL}" \
  --user-attributes Name=email,Value="${EMAIL}" Name=email_verified,Value=true \
  --message-action SUPPRESS \
  --temporary-password 'TempBootstrap1!' \
  --region "${REGION}" > /dev/null

# Set permanent password (skips forced change on first login)
aws cognito-idp admin-set-user-password \
  --user-pool-id "${USER_POOL_ID}" \
  --username "${EMAIL}" \
  --password "${PASSWORD}" \
  --permanent \
  --region "${REGION}"

# Assign to group
if [ -n "${GROUP_NAME}" ]; then
  aws cognito-idp admin-add-user-to-group \
    --user-pool-id "${USER_POOL_ID}" \
    --username "${EMAIL}" \
    --group-name "${GROUP_NAME}" \
    --region "${REGION}"
fi

# ── Summary ──
echo ""
echo "✓ User created successfully"
echo "  Email:    ${EMAIL}"
echo "  Password: ${PASSWORD}"
if [ -n "${GROUP_NAME}" ]; then
  echo "  Group:    ${GROUP_NAME}"
else
  echo "  Group:    (none — no groups found in pool)"
fi
echo ""
echo "  The user can sign in immediately — no password change required."
