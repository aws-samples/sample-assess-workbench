#!/usr/bin/env bash
# Destroy the Terraform remote backend that `task destroy` deliberately
# preserves: the S3 state bucket, the DynamoDB lock table, and the
# `alias/terraform-state` KMS alias (its key scheduled for deletion). This is the
# cold-start reset — removing the alias makes the next `tf-bootstrap` recreate
# the key + alias from scratch, so the next deploy exercises the true cold path.
#
# Pairs with setup-terraform-backend.sh (same resource names) and is asserted by
# `task verify:clean --include-backend`. Sources with-env.sh, so the account
# guard refuses to run against the wrong account.
#
# ⚠️  DESTRUCTIVE and intended for a DEDICATED, otherwise-empty account (the
# clean-deploy canary). The state bucket and lock table are project-namespaced
# and safe, but `alias/terraform-state` is ACCOUNT+REGION-level and shared by
# every project that bootstrapped a backend here — deleting it in a shared
# account breaks the others' state encryption. Do not run this in dev/demo.
#
# pipefail (not `set -e`): each step is idempotent and tallied; a real failure
# exits non-zero at the end so verify:clean still sees a signal.

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=scripts/utils/with-env.sh
source "${SCRIPT_DIR}/with-env.sh"
# shellcheck source=scripts/common.sh
source "${SCRIPT_DIR}/../common.sh"  # is_not_found

: "${AWS_REGION:?destroy-backend: AWS_REGION must be set}"
: "${PROJECT_NAME:?destroy-backend: PROJECT_NAME must be set}"
: "${ENVIRONMENT:?destroy-backend: ENVIRONMENT must be set}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"

BUCKET_NAME="${PROJECT_NAME}-terraform-state-${AWS_ACCOUNT_ID}"
TABLE_NAME="${PROJECT_NAME}-terraform-locks"
KMS_ALIAS="alias/terraform-state"
BACKEND_FILE="${REPO_ROOT}/terraform/backends/${ENVIRONMENT}.hcl"

FAILURES=0

echo "=================================="
echo "Destroy Terraform Backend"
echo "=================================="
echo "  Project:     ${PROJECT_NAME}"
echo "  Environment: ${ENVIRONMENT}"
echo "  Region:      ${AWS_REGION}"
echo "  Account:     ${AWS_ACCOUNT_ID}"
echo "  Bucket:      ${BUCKET_NAME}"
echo "  Lock table:  ${TABLE_NAME}"
echo "  KMS alias:   ${KMS_ALIAS} (account-level — shared across projects)"
echo ""

# ── State bucket (versioned) ──────────────────────────────────────
echo "── State bucket ──"
if ! aws s3api head-bucket --bucket "${BUCKET_NAME}" --region "${AWS_REGION}" 2>/dev/null; then
    echo "  (bucket already gone)"
else
    # Drop current objects, then every version and delete-marker. Mirrors
    # destroy_knowledge_bases.sh::delete_s3_bucket — a state bucket is small, so
    # a single list per selector (no pagination) is sufficient.
    aws s3 rm "s3://${BUCKET_NAME}" --recursive --region "${AWS_REGION}" >/dev/null 2>&1 || true

    for selector in Versions DeleteMarkers; do
        page=$(aws s3api list-object-versions --bucket "${BUCKET_NAME}" \
            --region "${AWS_REGION}" \
            --query "{Objects: ${selector}[].{Key:Key,VersionId:VersionId}}" \
            --output json 2>/dev/null || echo '{"Objects": null}')
        if printf '%s' "$page" | python3 -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('Objects') else 1)" 2>/dev/null; then
            aws s3api delete-objects --bucket "${BUCKET_NAME}" --region "${AWS_REGION}" \
                --delete "$page" >/dev/null 2>&1 || true
        fi
    done

    if err=$(aws s3 rb "s3://${BUCKET_NAME}" --region "${AWS_REGION}" 2>&1); then
        echo "  ✓ Bucket deleted"
    else
        echo "  ⚠️  Could not delete bucket ${BUCKET_NAME}: ${err}"
        FAILURES=$((FAILURES + 1))
    fi
fi
echo ""

# ── Lock table ────────────────────────────────────────────────────
echo "── Lock table ──"
if err=$(aws dynamodb delete-table --table-name "${TABLE_NAME}" --region "${AWS_REGION}" 2>&1); then
    echo "  ✓ Lock table deleted"
elif is_not_found "$err"; then
    echo "  (lock table already gone)"
else
    echo "  ⚠️  Could not delete lock table ${TABLE_NAME}: ${err}"
    FAILURES=$((FAILURES + 1))
fi
echo ""

# ── KMS alias + key ───────────────────────────────────────────────
# Delete the (account-level) alias, then schedule its key for deletion — KMS
# allows only scheduling, min 7-day window. Removing the alias is what makes the
# next bootstrap recreate the key + alias.
echo "── KMS alias + key ──"
KMS_KEY_ID=$(aws kms list-aliases --region "${AWS_REGION}" \
    --query "Aliases[?AliasName=='${KMS_ALIAS}'].TargetKeyId | [0]" --output text 2>/dev/null)

if [ -z "$KMS_KEY_ID" ] || [ "$KMS_KEY_ID" = "None" ]; then
    echo "  (alias ${KMS_ALIAS} already gone)"
else
    if err=$(aws kms delete-alias --alias-name "${KMS_ALIAS}" --region "${AWS_REGION}" 2>&1); then
        echo "  ✓ Alias deleted"
    else
        echo "  ⚠️  Could not delete alias ${KMS_ALIAS}: ${err}"
        FAILURES=$((FAILURES + 1))
    fi

    if err=$(aws kms schedule-key-deletion --key-id "${KMS_KEY_ID}" \
        --pending-window-in-days 7 --region "${AWS_REGION}" 2>&1); then
        echo "  ✓ Key ${KMS_KEY_ID} scheduled for deletion (7-day window)"
    elif printf '%s' "$err" | grep -qiE 'pending deletion|KMSInvalidStateException'; then
        echo "  (key ${KMS_KEY_ID} already scheduled for deletion)"
    else
        echo "  ⚠️  Could not schedule key ${KMS_KEY_ID} for deletion: ${err}"
        FAILURES=$((FAILURES + 1))
    fi
fi
echo ""

# ── Local backend config ──────────────────────────────────────────
# Gitignored, account-specific, and regenerated by tf-bootstrap when absent;
# remove it so the next bootstrap re-derives it for a clean run.
if [ -f "${BACKEND_FILE}" ]; then
    rm -f "${BACKEND_FILE}"
    echo "Removed local backend config: terraform/backends/${ENVIRONMENT}.hcl"
fi

echo ""
echo "=================================="
if [ "$FAILURES" -eq 0 ]; then
    echo "✓ Terraform backend destroyed"
    echo "=================================="
else
    echo "❌ Backend teardown: ${FAILURES} step(s) failed (see warnings above)."
    echo "=================================="
    exit 1
fi
