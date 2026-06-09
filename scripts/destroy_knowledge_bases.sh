#!/bin/bash
# Destroy Knowledge Bases and all associated resources.
#
# Cleans up both the Document Index KB and Standards KB:
#   - Bedrock data sources and knowledge bases
#   - S3 Vectors indexes and buckets
#   - IAM service roles
#   - Standards corpus S3 bucket
#
# SSM parameters are NOT deleted here — destroy:ssm handles that.
#
# Safe to run when resources don't exist (idempotent).

set -e

source "$(dirname "$0")/common.sh"

echo "=================================="
echo "Destroy Knowledge Bases"
echo "=================================="
echo ""

init_deployment

# ── Helpers ──────────────────────────────────────────────────────

# Delete a Bedrock Knowledge Base and its data sources.
# Args: $1 = KB ID, $2 = human-readable label
delete_knowledge_base() {
    local kb_id="$1"
    local label="$2"

    echo "Deleting ${label} (${kb_id})..."

    # List and delete all data sources first
    local ds_ids
    ds_ids=$(aws bedrock-agent list-data-sources \
        --knowledge-base-id "${kb_id}" \
        --region "${AWS_REGION}" \
        --query 'dataSourceSummaries[].dataSourceId' \
        --output text 2>/dev/null || echo "")

    for ds_id in $ds_ids; do
        if [ -n "$ds_id" ] && [ "$ds_id" != "None" ]; then
            echo "  Deleting data source: ${ds_id}"
            aws bedrock-agent delete-data-source \
                --knowledge-base-id "${kb_id}" \
                --data-source-id "${ds_id}" \
                --region "${AWS_REGION}" > /dev/null 2>&1 || \
                echo "  ⚠️  Could not delete data source ${ds_id}"
        fi
    done

    # Delete the knowledge base
    aws bedrock-agent delete-knowledge-base \
        --knowledge-base-id "${kb_id}" \
        --region "${AWS_REGION}" > /dev/null 2>&1 || {
        echo "  ⚠️  Could not delete KB ${kb_id}"
        return 1
    }

    # Wait for deletion
    echo "  Waiting for KB deletion..."
    local timeout=120
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        local status
        status=$(aws bedrock-agent get-knowledge-base \
            --knowledge-base-id "${kb_id}" \
            --region "${AWS_REGION}" \
            --query 'knowledgeBase.status' \
            --output text 2>/dev/null || echo "DELETED")

        if [ "$status" = "DELETED" ] || [ "$status" = "DELETE_UNSUCCESSFUL" ]; then
            break
        fi

        sleep 5
        elapsed=$((elapsed + 5))
    done

    if [ "$status" = "DELETE_UNSUCCESSFUL" ]; then
        echo "  ❌ KB deletion failed — may need manual cleanup"
        return 1
    fi

    echo "  ✓ ${label} deleted"
}

# Delete an S3 Vectors index and its bucket.
# Args: $1 = vector bucket name, $2 = index name
delete_vector_store() {
    local bucket_name="$1"
    local index_name="$2"

    echo "Deleting S3 Vectors: ${bucket_name}/${index_name}..."

    # Delete the index first
    aws s3vectors delete-index \
        --vector-bucket-name "${bucket_name}" \
        --index-name "${index_name}" \
        --region "${AWS_REGION}" > /dev/null 2>&1 || \
        echo "  (index not found or already deleted)"

    # Delete the vector bucket
    aws s3vectors delete-vector-bucket \
        --vector-bucket-name "${bucket_name}" \
        --region "${AWS_REGION}" > /dev/null 2>&1 || \
        echo "  (vector bucket not found or already deleted)"

    echo "  ✓ Vector store cleaned up"
}

# Delete an IAM service role and its inline policies.
# Args: $1 = role name
delete_iam_role() {
    local role_name="$1"

    echo "Deleting IAM role: ${role_name}..."

    # Check if role exists
    if ! aws iam get-role --role-name "${role_name}" > /dev/null 2>&1; then
        echo "  (role not found)"
        return 0
    fi

    # Delete all inline policies
    local policies
    policies=$(aws iam list-role-policies \
        --role-name "${role_name}" \
        --query 'PolicyNames[]' \
        --output text 2>/dev/null || echo "")

    for policy in $policies; do
        if [ -n "$policy" ] && [ "$policy" != "None" ]; then
            aws iam delete-role-policy \
                --role-name "${role_name}" \
                --policy-name "${policy}" 2>/dev/null || true
        fi
    done

    # Detach any managed policies
    local attached
    attached=$(aws iam list-attached-role-policies \
        --role-name "${role_name}" \
        --query 'AttachedPolicies[].PolicyArn' \
        --output text 2>/dev/null || echo "")

    for arn in $attached; do
        if [ -n "$arn" ] && [ "$arn" != "None" ]; then
            aws iam detach-role-policy \
                --role-name "${role_name}" \
                --policy-arn "${arn}" 2>/dev/null || true
        fi
    done

    aws iam delete-role --role-name "${role_name}" 2>/dev/null || {
        echo "  ⚠️  Could not delete role ${role_name}"
        return 1
    }

    echo "  ✓ Role deleted"
}

# Empty and delete an S3 bucket.
# Args: $1 = bucket name
delete_s3_bucket() {
    local bucket_name="$1"

    echo "Deleting S3 bucket: ${bucket_name}..."

    if ! aws s3api head-bucket --bucket "${bucket_name}" 2>/dev/null; then
        echo "  (bucket not found)"
        return 0
    fi

    # Empty the bucket (including versioned objects)
    aws s3 rm "s3://${bucket_name}" --recursive --region "${AWS_REGION}" > /dev/null 2>&1 || true

    # Delete any remaining versioned objects and delete markers
    local versions
    versions=$(aws s3api list-object-versions \
        --bucket "${bucket_name}" \
        --region "${AWS_REGION}" \
        --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
        --output json 2>/dev/null || echo '{"Objects": null}')

    if echo "$versions" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('Objects') else 1)" 2>/dev/null; then
        aws s3api delete-objects \
            --bucket "${bucket_name}" \
            --region "${AWS_REGION}" \
            --delete "${versions}" > /dev/null 2>&1 || true
    fi

    local markers
    markers=$(aws s3api list-object-versions \
        --bucket "${bucket_name}" \
        --region "${AWS_REGION}" \
        --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
        --output json 2>/dev/null || echo '{"Objects": null}')

    if echo "$markers" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('Objects') else 1)" 2>/dev/null; then
        aws s3api delete-objects \
            --bucket "${bucket_name}" \
            --region "${AWS_REGION}" \
            --delete "${markers}" > /dev/null 2>&1 || true
    fi

    aws s3 rb "s3://${bucket_name}" --region "${AWS_REGION}" 2>/dev/null || {
        echo "  ⚠️  Could not delete bucket ${bucket_name}"
        return 1
    }

    echo "  ✓ Bucket deleted"
}

# ── Document Index KB ────────────────────────────────────────────
echo "── Document Index KB ──"
echo ""

DOC_KB_ID=$(ssm_get "kb/document_kb_id" 2>/dev/null || echo "")

if [ -n "$DOC_KB_ID" ] && [ "$DOC_KB_ID" != "None" ]; then
    delete_knowledge_base "${DOC_KB_ID}" "Document Index KB"
else
    echo "No Document Index KB found in SSM — skipping KB deletion"
fi

DOC_VECTOR_BUCKET="${PROJECT_NAME}-document-kb-${ENVIRONMENT}"
delete_vector_store "${DOC_VECTOR_BUCKET}" "bedrock-knowledge-base-default-index"

DOC_ROLE_NAME="${PROJECT_NAME}-document-kb-${ENVIRONMENT}"
delete_iam_role "${DOC_ROLE_NAME}"

echo ""

# ── Standards KB ─────────────────────────────────────────────────
echo "── Standards KB ──"
echo ""

STD_KB_ID=$(ssm_get "kb/standards_kb_id" 2>/dev/null || echo "")

if [ -n "$STD_KB_ID" ] && [ "$STD_KB_ID" != "None" ]; then
    delete_knowledge_base "${STD_KB_ID}" "Standards KB"
else
    echo "No Standards KB found in SSM — skipping KB deletion"
fi

STD_VECTOR_BUCKET="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
delete_vector_store "${STD_VECTOR_BUCKET}" "bedrock-knowledge-base-default-index"

STD_ROLE_NAME="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
delete_iam_role "${STD_ROLE_NAME}"

# Standards corpus S3 bucket
STD_CORPUS_BUCKET="${PROJECT_NAME}-standards-${ENVIRONMENT}-${AWS_ACCOUNT_ID}"
delete_s3_bucket "${STD_CORPUS_BUCKET}"

echo ""
echo "=================================="
echo "Knowledge Base cleanup complete ✓"
echo "=================================="
