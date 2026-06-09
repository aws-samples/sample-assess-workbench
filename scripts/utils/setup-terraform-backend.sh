#!/bin/bash
# Setup Terraform backend infrastructure (S3 + DynamoDB + KMS)
# Run this ONCE before using Terraform

set -e

echo "=================================="
echo "Setup Terraform Backend"
echo "=================================="
echo ""

# Load environment
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    source "${REPO_ROOT}/.env"
    set +a
    echo "✓ Loaded configuration from .env"
else
    echo "⚠️  No .env file found, using defaults"
fi

AWS_REGION="${AWS_REGION:-us-west-2}"
PROJECT_NAME="${PROJECT_NAME:-risk-assessor}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

BUCKET_NAME="${PROJECT_NAME}-terraform-state-${AWS_ACCOUNT_ID}"
TABLE_NAME="${PROJECT_NAME}-terraform-locks"
KMS_ALIAS="alias/terraform-state"

BACKEND_TEMPLATE="${REPO_ROOT}/terraform/backends/example.hcl.template"
BACKEND_FILE="${REPO_ROOT}/terraform/backends/${ENVIRONMENT}.hcl"

echo "Configuration:"
echo "  Region: ${AWS_REGION}"
echo "  Account: ${AWS_ACCOUNT_ID}"
echo "  Environment: ${ENVIRONMENT}"
echo "  Bucket: ${BUCKET_NAME}"
echo "  DynamoDB Table: ${TABLE_NAME}"
echo "  KMS Alias: ${KMS_ALIAS}"
echo "  Backend config: terraform/backends/${ENVIRONMENT}.hcl"
echo ""

# Check if bucket already exists
if aws s3 ls "s3://${BUCKET_NAME}" 2>/dev/null; then
    echo "✓ S3 bucket already exists: ${BUCKET_NAME}"
else
    echo "Creating S3 bucket for Terraform state..."
    aws s3 mb "s3://${BUCKET_NAME}" --region "${AWS_REGION}"
    
    # Enable versioning
    aws s3api put-bucket-versioning \
        --bucket "${BUCKET_NAME}" \
        --versioning-configuration Status=Enabled \
        --region "${AWS_REGION}"
    
    # Enable encryption
    aws s3api put-bucket-encryption \
        --bucket "${BUCKET_NAME}" \
        --server-side-encryption-configuration '{
            "Rules": [{
                "ApplyServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                },
                "BucketKeyEnabled": true
            }]
        }' \
        --region "${AWS_REGION}"
    
    # Block public access
    aws s3api put-public-access-block \
        --bucket "${BUCKET_NAME}" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
        --region "${AWS_REGION}"
    
    echo "✓ S3 bucket created and configured"
fi

# Check if DynamoDB table exists
if aws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${AWS_REGION}" 2>/dev/null >/dev/null; then
    echo "✓ DynamoDB table already exists: ${TABLE_NAME}"
else
    echo "Creating DynamoDB table for state locking..."
    aws dynamodb create-table \
        --table-name "${TABLE_NAME}" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region "${AWS_REGION}" \
        --tags Key=Project,Value="${PROJECT_NAME}" Key=ManagedBy,Value=Terraform
    
    echo "⏳ Waiting for table to be active..."
    aws dynamodb wait table-exists --table-name "${TABLE_NAME}" --region "${AWS_REGION}"
    echo "✓ DynamoDB table created"
fi

# Check if KMS key exists
KMS_KEY_ID=$(aws kms list-aliases --region "${AWS_REGION}" --query "Aliases[?AliasName=='${KMS_ALIAS}'].TargetKeyId" --output text)

if [ -n "$KMS_KEY_ID" ]; then
    echo "✓ KMS key already exists: ${KMS_ALIAS}"
else
    echo "Creating KMS key for state encryption..."
    KMS_KEY_ID=$(aws kms create-key \
        --description "Terraform state encryption for ${PROJECT_NAME}" \
        --region "${AWS_REGION}" \
        --tags TagKey=Project,TagValue="${PROJECT_NAME}" TagKey=ManagedBy,TagValue=Terraform \
        --query 'KeyMetadata.KeyId' \
        --output text)
    
    aws kms create-alias \
        --alias-name "${KMS_ALIAS}" \
        --target-key-id "${KMS_KEY_ID}" \
        --region "${AWS_REGION}"
    
    echo "✓ KMS key created: ${KMS_ALIAS}"
fi

# ── Generate the Terraform backend config for this environment ──
# The account is derived once (STS, above) and flows into the bucket name here,
# so the backend file never needs to be hand-edited. Generated only when absent;
# the file is gitignored and account-specific, so an existing one is left as-is.
if [ -f "${BACKEND_FILE}" ]; then
    echo "✓ Backend config already exists: terraform/backends/${ENVIRONMENT}.hcl (left unchanged)"
elif [ ! -f "${BACKEND_TEMPLATE}" ]; then
    echo "❌ Backend template not found: ${BACKEND_TEMPLATE}" >&2
    exit 1
else
    echo "Generating backend config: terraform/backends/${ENVIRONMENT}.hcl"
    sed -e "s/<PROJECT_NAME>/${PROJECT_NAME}/g" \
        -e "s/<ACCOUNT_ID>/${AWS_ACCOUNT_ID}/g" \
        -e "s/<AWS_REGION>/${AWS_REGION}/g" \
        "${BACKEND_TEMPLATE}" > "${BACKEND_FILE}"
    echo "✓ Backend config generated"
fi

echo ""
echo "=================================="
echo "Backend Setup Complete! ✓"
echo "=================================="
echo ""
echo "Backend configuration:"
echo "  bucket         = \"${BUCKET_NAME}\""
echo "  region         = \"${AWS_REGION}\""
echo "  dynamodb_table = \"${TABLE_NAME}\""
echo "  kms_key_id     = \"${KMS_ALIAS}\""
echo ""
echo "Next step:"
echo "  Run 'task deploy' to deploy the full stack (terraform init with this"
echo "  backend happens automatically via backends/\${ENVIRONMENT}.hcl)."
