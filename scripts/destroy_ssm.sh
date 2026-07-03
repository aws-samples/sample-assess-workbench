#!/usr/bin/env bash
# Delete all SSM parameters under /<project>/<env>.
#
# Destructive but idempotent (no-op when none exist). Self-guarding: sources
# with-env.sh, which asserts the live AWS account matches the resolved
# environment before anything is deleted. Invoked by `task destroy:ssm`.
#
# pipefail (not `set -e`): individual deletes use `|| true` and the loop is
# meant to plow through failures rather than abort the teardown.

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh

: "${PROJECT_NAME:?destroy_ssm: PROJECT_NAME must be set}"
: "${ENVIRONMENT:?destroy_ssm: ENVIRONMENT must be set}"
: "${AWS_REGION:?destroy_ssm: AWS_REGION must be set}"

PREFIX="/${PROJECT_NAME}/${ENVIRONMENT}"
echo "Cleaning up SSM parameters under ${PREFIX}..."
PARAMS=$(aws ssm get-parameters-by-path \
  --path "${PREFIX}" \
  --recursive \
  --query 'Parameters[].Name' \
  --output text \
  --region "${AWS_REGION}" 2>/dev/null || true)

if [ -z "$PARAMS" ]; then
  echo "No SSM parameters found under ${PREFIX}"
  exit 0
fi

for PARAM in $PARAMS; do
  echo "  Deleting ${PARAM}..."
  aws ssm delete-parameter --name "${PARAM}" --region "${AWS_REGION}" 2>/dev/null || true
done
echo "✓ SSM parameters cleaned up"
