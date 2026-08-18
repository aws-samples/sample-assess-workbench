#!/usr/bin/env bash
# Deploy the built frontend to S3 and invalidate CloudFront.
#
# Reads the edge module's Terraform outputs, syncs frontend/dist/ to the edge
# bucket, overwrites config.json with the Terraform-generated version, and
# invalidates index.html + config.json. Self-guarding: sources with-env.sh,
# which asserts the live AWS account matches the resolved environment. Invoked by
# `task deploy:frontend` (which builds the frontend first).
#
# pipefail (not `set -e`): matches the original task block; the explicit checks
# below handle the failure that matters (missing edge outputs).

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh

: "${ENVIRONMENT:?deploy_frontend: ENVIRONMENT must be set}"
: "${AWS_REGION:?deploy_frontend: AWS_REGION must be set}"

export TF_DATA_DIR=".terraform/${ENVIRONMENT}"

BUCKET=$(terraform -chdir=terraform output -raw edge_bucket_name 2>/dev/null)
DIST_ID=$(terraform -chdir=terraform output -raw edge_distribution_id 2>/dev/null)
if [ -z "$BUCKET" ] || [ -z "$DIST_ID" ]; then
  echo "❌ Could not read edge module outputs."
  echo "   Set deploy_frontend = true in your tfvars and run:"
  echo "     ENVIRONMENT=${ENVIRONMENT} task deploy:infra"
  exit 1
fi

echo "Syncing frontend/dist/ → s3://${BUCKET}"
aws s3 sync frontend/dist/ "s3://${BUCKET}" --delete --region "${AWS_REGION}"

# Overwrite config.json with the Terraform-generated version. The build step
# snapshots public/config.json into dist/ at build time, which may be stale.
# This ensures the deployed config always matches the latest Terraform output
# (relative URLs when API proxy is enabled, direct URLs otherwise).
echo "Overwriting config.json with Terraform-generated config"
aws s3 cp frontend/public/config.json "s3://${BUCKET}/config.json" --region "${AWS_REGION}"

# Only index.html and config.json need invalidation — content-hashed assets are
# served by new filenames and both are CachingDisabled in CloudFront
# (belt-and-braces so deploys are always fresh).
echo "Invalidating /index.html and /config.json on ${DIST_ID}"
aws cloudfront create-invalidation \
  --distribution-id "${DIST_ID}" \
  --paths "/index.html" "/config.json" \
  --output text > /dev/null

URL=$(terraform -chdir=terraform output -raw frontend_url 2>/dev/null)
echo "✓ Frontend deployed: ${URL}"
