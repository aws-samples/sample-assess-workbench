#!/bin/bash
# Deploy Document Index Knowledge Base to Bedrock.
# Creates a KB with a custom data source backed by S3 Vectors.
# Documents are ingested inline via IngestKnowledgeBaseDocuments
# (no S3 staging bucket needed for the data source itself).
#
# The CreateKnowledgeBase API requires a pre-created S3 Vectors index ARN —
# passing an empty s3VectorsConfiguration causes a misleading "unable to
# assume role" error. This script creates the vector bucket + index first.
#
# The CUSTOM data source type is not yet in the CLI/boto3 service model's
# DataSourceConfiguration shape, so we use boto3 with type='CUSTOM' only
# (omitting the customConfiguration key) to bypass client-side validation.
#
# Uses AWS CLI + Python (boto3) — no jq needed.

set -e

source "$(dirname "$0")/common.sh"

echo "=================================="
echo "Deploy Document Index Knowledge Base"
echo "=================================="
echo ""

init_deployment

KB_NAME="${PROJECT_NAME}-document-index-${ENVIRONMENT}"
VECTOR_BUCKET_NAME="${PROJECT_NAME}-document-kb-${ENVIRONMENT}"
VECTOR_INDEX_NAME="bedrock-knowledge-base-default-index"
EMBEDDING_MODEL="amazon.titan-embed-text-v2:0"
# Titan v2 embeddings are L2-normalized, so cosine is the correct metric and
# yields interpretable 0–1 similarity scores. The metric is fixed at index
# creation; changing it on an existing index requires deleting and recreating
# it, which drops all indexed project documents (they re-ingest per project).
DISTANCE_METRIC="cosine"

echo "KB Name:         ${KB_NAME}"
echo "Vector Bucket:   ${VECTOR_BUCKET_NAME}"
echo "Embedding Model: ${EMBEDDING_MODEL}"
echo "Region:          ${AWS_REGION}"
echo ""

# ── Check for existing KB ────────────────────────────────────────
echo "Checking for existing Document Index KB..."
EXISTING_KB_ID=$(ssm_get "kb/document_kb_id" 2>/dev/null || echo "")

if [ -n "$EXISTING_KB_ID" ] && [ "$EXISTING_KB_ID" != "None" ]; then
  echo "  Found existing KB: ${EXISTING_KB_ID}"

  KB_STATUS=$(aws bedrock-agent get-knowledge-base \
    --knowledge-base-id "${EXISTING_KB_ID}" \
    --region "${AWS_REGION}" \
    --query 'knowledgeBase.status' --output text 2>/dev/null || echo "NOT_FOUND")

  if [ "$KB_STATUS" = "ACTIVE" ]; then
    echo "  Status: ACTIVE — using existing KB"

    DS_ID=$(ssm_get "kb/document_ds_id" 2>/dev/null || echo "")
    if [ -n "$DS_ID" ] && [ "$DS_ID" != "None" ]; then
      echo "  Data Source: ${DS_ID}"
      echo ""
      echo "================================"
      echo "Already deployed ✓"
      echo "================================"
      exit 0
    fi
    echo "  ⚠️  Data source ID not in SSM — will recreate"
  else
    echo "  KB status: ${KB_STATUS} — will create new"
  fi
fi

# ── Create S3 Vectors bucket + index ─────────────────────────────
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
  --distance-metric "${DISTANCE_METRIC}" \
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

# ── Create IAM role for Bedrock KB ───────────────────────────────
ROLE_NAME="${PROJECT_NAME}-document-kb-${ENVIRONMENT}"
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

aws iam update-assume-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-document "${TRUST_POLICY}"

echo "  Role ARN: ${ROLE_ARN}"

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
  --policy-document "${POLICY_DOC}"

echo "  ✓ IAM role configured"

echo "Waiting for IAM role to propagate..."
sleep 10

# ── Create Knowledge Base ────────────────────────────────────────
echo "Creating Knowledge Base: ${KB_NAME}..."

KB_CREATE_ATTEMPTS=0
KB_CREATE_MAX=3
KB_ID=""
while [ $KB_CREATE_ATTEMPTS -lt $KB_CREATE_MAX ]; do
  KB_CREATE_ATTEMPTS=$((KB_CREATE_ATTEMPTS + 1))
  KB_ID=$(aws bedrock-agent create-knowledge-base \
    --name "${KB_NAME}" \
    --description "Document Index KB for project document semantic search" \
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

# ── Wait for KB to become ACTIVE ─────────────────────────────────
echo "Waiting for KB to become ACTIVE..."
TIMEOUT=120
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
  STATUS=$(aws bedrock-agent get-knowledge-base \
    --knowledge-base-id "${KB_ID}" \
    --region "${AWS_REGION}" \
    --query 'knowledgeBase.status' --output text 2>/dev/null)

  if [ "$STATUS" = "ACTIVE" ]; then
    break
  elif [ "$STATUS" = "FAILED" ]; then
    echo "  ❌ KB creation failed"
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
echo "  ✓ KB active"

# ── Create Custom Data Source ────────────────────────────────────
# The CUSTOM data source type is in the API but the CLI/boto3 service model
# is missing the customConfiguration shape member. Passing type='CUSTOM'
# without the config key bypasses client-side validation and the API accepts it.
echo "Creating custom data source..."

DS_ID=$(python3 -c "
import boto3, os
session = boto3.Session(
    profile_name=(os.environ.get('AWS_PROFILE') or None),
    region_name=(os.environ.get('AWS_REGION') or None),
)
client = session.client('bedrock-agent')
resp = client.create_data_source(
    knowledgeBaseId='${KB_ID}',
    name='${KB_NAME}-custom-ds',
    description='Custom data source for inline document ingestion',
    dataSourceConfiguration={'type': 'CUSTOM'},
    vectorIngestionConfiguration={
        'chunkingConfiguration': {
            'chunkingStrategy': 'HIERARCHICAL',
            'hierarchicalChunkingConfiguration': {
                'levelConfigurations': [
                    {'maxTokens': 1500},
                    {'maxTokens': 300}
                ],
                'overlapTokens': 60
            }
        }
    }
)
print(resp['dataSource']['dataSourceId'])
")

echo "  Data Source ID: ${DS_ID}"
echo "  ✓ Data source created"

# ── Store IDs in SSM ─────────────────────────────────────────────
echo ""
echo "Storing KB IDs in SSM..."
ssm_put "kb/document_kb_id" "${KB_ID}" "Document Index Knowledge Base ID"
ssm_put "kb/document_ds_id" "${DS_ID}" "Document Index Data Source ID"

echo ""
echo "================================"
echo "Deployment successful ✓"
echo "  KB ID:          ${KB_ID}"
echo "  Data Source ID: ${DS_ID}"
echo "================================"
