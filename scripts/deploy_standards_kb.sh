#!/bin/bash
# Deploy Standards Knowledge Base to Bedrock.
# Creates a KB with an S3 data source backed by S3 Vectors.
# Standards are markdown files in S3 with JSON metadata sidecars.
#
# Usage:
#   ./scripts/deploy_standards_kb.sh          # Create KB + upload corpus + sync
#   ./scripts/deploy_standards_kb.sh --sync   # Upload corpus + sync only (KB exists)
#
# Uses AWS CLI — no jq needed (JMESPath queries via --query).

set -e

source "$(dirname "$0")/common.sh"

echo "=================================="
echo "Deploy Standards Knowledge Base"
echo "=================================="
echo ""

init_deployment

KB_NAME="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
BUCKET_NAME="${PROJECT_NAME}-standards-${ENVIRONMENT}-${AWS_ACCOUNT_ID}"
VECTOR_BUCKET_NAME="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
VECTOR_INDEX_NAME="bedrock-knowledge-base-default-index"
EMBEDDING_MODEL="amazon.titan-embed-text-v2:0"
STANDARDS_DIR="$(dirname "$0")/../standards"
SYNC_ONLY=false

if [ "${1:-}" = "--sync" ]; then
  SYNC_ONLY=true
  echo "Mode: sync only (upload corpus + trigger sync)"
else
  echo "Mode: full deployment"
fi

echo "KB Name:         ${KB_NAME}"
echo "S3 Bucket:       ${BUCKET_NAME}"
echo "Embedding Model: ${EMBEDDING_MODEL}"
echo "Standards Dir:   ${STANDARDS_DIR}"
echo "Region:          ${AWS_REGION}"
echo ""

# ── Check for existing KB ────────────────────────────────────────
EXISTING_KB_ID=$(ssm_get "kb/standards_kb_id" 2>/dev/null || echo "")

if [ "$SYNC_ONLY" = true ]; then
  if [ -z "$EXISTING_KB_ID" ] || [ "$EXISTING_KB_ID" = "None" ]; then
    echo "❌ No existing Standards KB found in SSM. Run without --sync first."
    exit 1
  fi
  KB_ID="$EXISTING_KB_ID"
  echo "Using existing KB: ${KB_ID}"
else
  if [ -n "$EXISTING_KB_ID" ] && [ "$EXISTING_KB_ID" != "None" ]; then
    KB_STATUS=$(aws bedrock-agent get-knowledge-base \
      --knowledge-base-id "${EXISTING_KB_ID}" \
      --region "${AWS_REGION}" \
      --query 'knowledgeBase.status' --output text 2>/dev/null || echo "NOT_FOUND")

    if [ "$KB_STATUS" = "ACTIVE" ]; then
      echo "Found existing KB: ${EXISTING_KB_ID} (ACTIVE)"
      KB_ID="$EXISTING_KB_ID"
    else
      echo "Existing KB status: ${KB_STATUS} — will create new"
    fi
  fi
fi

# ── Create S3 bucket for standards corpus ────────────────────────
if ! aws s3api head-bucket --bucket "${BUCKET_NAME}" 2>/dev/null; then
  echo "Creating S3 bucket: ${BUCKET_NAME}..."
  if [ "${AWS_REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET_NAME}" --region "${AWS_REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET_NAME}" --region "${AWS_REGION}" \
      --create-bucket-configuration LocationConstraint="${AWS_REGION}"
  fi
  echo "  ✓ Bucket created"
else
  echo "S3 bucket exists: ${BUCKET_NAME}"
fi

# ── Create KB if needed ──────────────────────────────────────────
if [ -z "${KB_ID:-}" ]; then
  # ── Create S3 Vectors bucket + index ───────────────────────────
  # The CreateKnowledgeBase API requires a pre-created index ARN.
  # The Bedrock console does this automatically; the CLI does not.
  echo "Creating S3 Vectors bucket: ${VECTOR_BUCKET_NAME}..."
  aws s3vectors create-vector-bucket \
    --vector-bucket-name "${VECTOR_BUCKET_NAME}" \
    --region "${AWS_REGION}" 2>/dev/null || echo "  (bucket already exists)"

  echo "Creating S3 Vectors index: ${VECTOR_INDEX_NAME}..."
  INDEX_ARN=$(aws s3vectors create-index \
    --vector-bucket-name "${VECTOR_BUCKET_NAME}" \
    --index-name "${VECTOR_INDEX_NAME}" \
    --data-type float32 \
    --dimension 1024 \
    --distance-metric euclidean \
    --metadata-configuration '{"nonFilterableMetadataKeys":["AMAZON_BEDROCK_TEXT","AMAZON_BEDROCK_METADATA"]}' \
    --region "${AWS_REGION}" \
    --query 'indexArn' --output text 2>/dev/null || \
    aws s3vectors get-index \
      --vector-bucket-name "${VECTOR_BUCKET_NAME}" \
      --index-name "${VECTOR_INDEX_NAME}" \
      --region "${AWS_REGION}" \
      --query 'index.indexArn' --output text)

  echo "  Index ARN: ${INDEX_ARN}"
  echo "  ✓ S3 Vectors ready"

  # Create IAM role for Bedrock KB
  ROLE_NAME="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
  echo "Creating IAM role: ${ROLE_NAME}..."

  TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {
        "aws:SourceAccount": "${AWS_ACCOUNT_ID}"
      },
      "ArnLike": {
        "AWS:SourceArn": "arn:aws:bedrock:${AWS_REGION}:${AWS_ACCOUNT_ID}:knowledge-base/*"
      }
    }
  }]
}
EOF
)

  ROLE_ARN=$(aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --path "/service-role/" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --query 'Role.Arn' --output text 2>/dev/null || \
    aws iam get-role --role-name "${ROLE_NAME}" \
    --query 'Role.Arn' --output text)

  # Ensure trust policy is current — if the role already existed,
  # create-role was a no-op and the trust policy may be stale.
  aws iam update-assume-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-document "${TRUST_POLICY}" 2>/dev/null || true

  POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:ListFoundationModels",
        "bedrock:ListCustomModels"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": [
        "arn:aws:bedrock:${AWS_REGION}::foundation-model/${EMBEDDING_MODEL}"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::${BUCKET_NAME}",
        "arn:aws:s3:::${BUCKET_NAME}/*"
      ]
    },
    {
      "Sid": "S3VectorsAccess",
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:GetIndex",
        "s3vectors:ListIndexes",
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors"
      ],
      "Resource": "arn:aws:s3vectors:${AWS_REGION}:${AWS_ACCOUNT_ID}:*"
    },
    {
      "Sid": "S3VectorsBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateBucket",
        "s3vectors:GetBucket",
        "s3vectors:ListBuckets"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

  aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "bedrock-kb-policy" \
    --policy-document "${POLICY_DOC}" > /dev/null 2>&1

  echo "  ✓ IAM role configured"

  # Wait for IAM role propagation — Bedrock needs to assume the role,
  # and IAM is eventually consistent. Retry the KB creation up to 3
  # times with increasing waits.
  echo "Waiting for IAM role to propagate..."
  sleep 10

  echo "Creating Knowledge Base: ${KB_NAME}..."

  KB_CREATE_ATTEMPTS=0
  KB_CREATE_MAX=3
  KB_ID=""
  while [ $KB_CREATE_ATTEMPTS -lt $KB_CREATE_MAX ]; do
    KB_CREATE_ATTEMPTS=$((KB_CREATE_ATTEMPTS + 1))
    KB_ID=$(aws bedrock-agent create-knowledge-base \
      --name "${KB_NAME}" \
      --description "Standards KB for compliance reference lookup" \
      --role-arn "${ROLE_ARN}" \
      --knowledge-base-configuration '{
        "type": "VECTOR",
        "vectorKnowledgeBaseConfiguration": {
          "embeddingModelArn": "arn:aws:bedrock:'"${AWS_REGION}"'::foundation-model/'"${EMBEDDING_MODEL}"'",
          "embeddingModelConfiguration": {
            "bedrockEmbeddingModelConfiguration": {
              "embeddingDataType": "FLOAT32"
            }
          }
        }
      }' \
      --storage-configuration '{
        "type": "S3_VECTORS",
        "s3VectorsConfiguration": {
          "indexArn": "'"${INDEX_ARN}"'"
        }
      }' \
      --region "${AWS_REGION}" \
      --query 'knowledgeBase.knowledgeBaseId' --output text 2>&1) && break

    if echo "$KB_ID" | grep -q "unable to assume the given role"; then
      echo "  IAM role not yet propagated (attempt ${KB_CREATE_ATTEMPTS}/${KB_CREATE_MAX}), waiting..."
      sleep $((KB_CREATE_ATTEMPTS * 15))
      KB_ID=""
    else
      echo "❌ Failed to create Knowledge Base: ${KB_ID}"
      exit 1
    fi
  done

  if [ -z "$KB_ID" ]; then
    echo "❌ Failed to create Knowledge Base after ${KB_CREATE_MAX} attempts (IAM propagation timeout)"
    exit 1
  fi

  echo "  KB ID: ${KB_ID}"

  # Wait for ACTIVE
  echo "Waiting for KB to become ACTIVE..."
  TIMEOUT=120
  ELAPSED=0
  while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(aws bedrock-agent get-knowledge-base \
      --knowledge-base-id "${KB_ID}" \
      --region "${AWS_REGION}" \
      --query 'knowledgeBase.status' --output text 2>/dev/null)

    if [ "$STATUS" = "ACTIVE" ]; then break; fi
    if [ "$STATUS" = "FAILED" ]; then echo "  ❌ KB creation failed"; exit 1; fi

    echo "  Waiting... (${STATUS}, ${ELAPSED}s)"
    sleep 5
    ELAPSED=$((ELAPSED + 5))
  done

  if [ "$STATUS" != "ACTIVE" ]; then echo "  ❌ Timeout"; exit 1; fi
  echo "  ✓ KB active"

  # Create S3 data source
  echo "Creating S3 data source..."

  DS_ID=$(aws bedrock-agent create-data-source \
    --knowledge-base-id "${KB_ID}" \
    --name "${KB_NAME}-s3-ds" \
    --description "S3 data source for standards corpus" \
    --data-source-configuration '{
      "type": "S3",
      "s3Configuration": {
        "bucketArn": "arn:aws:s3:::'${BUCKET_NAME}'"
      }
    }' \
    --vector-ingestion-configuration '{
      "chunkingConfiguration": {
        "chunkingStrategy": "HIERARCHICAL",
        "hierarchicalChunkingConfiguration": {
          "levelConfigurations": [
            {"maxTokens": 1500},
            {"maxTokens": 300}
          ],
          "overlapTokens": 60
        }
      }
    }' \
    --region "${AWS_REGION}" \
    --query 'dataSource.dataSourceId' --output text)

  echo "  Data Source ID: ${DS_ID}"

  # Store in SSM
  echo "Storing KB ID in SSM..."
  ssm_put "kb/standards_kb_id" "${KB_ID}" "Standards Knowledge Base ID"
  ssm_put "kb/standards_ds_id" "${DS_ID}" "Standards Data Source ID"
else
  DS_ID=$(ssm_get "kb/standards_ds_id" 2>/dev/null || echo "")
  if [ -z "$DS_ID" ] || [ "$DS_ID" = "None" ]; then
    echo "❌ Data source ID not found in SSM"
    exit 1
  fi
fi

# ── Upload standards corpus to S3 ───────────────────────────────
echo ""
echo "Uploading standards corpus to S3..."
if [ -d "${STANDARDS_DIR}" ]; then
  FILE_COUNT=$(find "${STANDARDS_DIR}" -name "*.md" | wc -l | tr -d ' ')
  echo "  Found ${FILE_COUNT} markdown files"
  aws s3 sync "${STANDARDS_DIR}" "s3://${BUCKET_NAME}/" \
    --exclude "*.DS_Store" --exclude "README.md" \
    --region "${AWS_REGION}"
  echo "  ✓ Corpus uploaded"
else
  echo "  ⚠️  Standards directory not found: ${STANDARDS_DIR}"
  echo "     Create standards/*.md files and re-run with --sync"
fi

# ── Trigger KB sync ──────────────────────────────────────────────
echo ""
echo "Triggering KB sync..."
INGESTION_JOB_ID=$(aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "${KB_ID}" \
  --data-source-id "${DS_ID}" \
  --region "${AWS_REGION}" \
  --query 'ingestionJob.ingestionJobId' --output text)

echo "  Ingestion job: ${INGESTION_JOB_ID}"

# Wait for sync to complete
echo "Waiting for sync to complete..."
TIMEOUT=300
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
  JOB_STATUS=$(aws bedrock-agent get-ingestion-job \
    --knowledge-base-id "${KB_ID}" \
    --data-source-id "${DS_ID}" \
    --ingestion-job-id "${INGESTION_JOB_ID}" \
    --region "${AWS_REGION}" \
    --query 'ingestionJob.status' --output text 2>/dev/null)

  if [ "$JOB_STATUS" = "COMPLETE" ]; then break; fi
  if [ "$JOB_STATUS" = "FAILED" ]; then
    echo "  ❌ Sync failed"
    aws bedrock-agent get-ingestion-job \
      --knowledge-base-id "${KB_ID}" \
      --data-source-id "${DS_ID}" \
      --ingestion-job-id "${INGESTION_JOB_ID}" \
      --region "${AWS_REGION}" \
      --query 'ingestionJob.failureReasons' --output text
    exit 1
  fi

  echo "  Waiting... (${JOB_STATUS}, ${ELAPSED}s)"
  sleep 10
  ELAPSED=$((ELAPSED + 10))
done

if [ "$JOB_STATUS" != "COMPLETE" ]; then echo "  ❌ Timeout"; exit 1; fi

echo "  ✓ Sync complete"
echo ""
echo "================================"
echo "Deployment successful ✓"
echo "  KB ID: ${KB_ID}"
echo "================================"
