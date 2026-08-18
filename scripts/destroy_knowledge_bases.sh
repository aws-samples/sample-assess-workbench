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
#
# pipefail (not `set -e`): like destroy_memory.sh / destroy_agents.sh, each
# cleanup step warns and is counted rather than aborting the teardown — a single
# orphan must not skip the rest. Real failures are tallied and the script exits
# non-zero at the end so the canary's verifier still sees a signal.

set -o pipefail

source "$(dirname "$0")/common.sh"

# Count of cleanup steps that failed for a real reason (not already-gone).
FAILURES=0

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
        echo "  ❌ KB ${kb_id} deletion failed (status DELETE_UNSUCCESSFUL)."
        echo "     Common cause: the vector store was removed before the KB, so"
        echo "     Bedrock cannot purge it. Set each data source's"
        echo "     dataDeletionPolicy to RETAIN, then retry:"
        echo "       aws bedrock-agent update-data-source --knowledge-base-id ${kb_id} \\"
        echo "         --data-source-id <id> --data-deletion-policy RETAIN \\"
        echo "         --name <name> --data-source-configuration <cfg> \\"
        echo "         --vector-ingestion-configuration <vic> --region ${AWS_REGION}"
        echo "       aws bedrock-agent delete-knowledge-base --knowledge-base-id ${kb_id} --region ${AWS_REGION}"
        return 1
    fi

    echo "  ✓ ${label} deleted"
}

# Delete an S3 Vectors index and its bucket.
# Distinguishes "already gone" (idempotent success) from a real failure, which
# is surfaced non-zero — a swallowed failure here silently orphans the whole
# vector store, the project's priciest-to-recreate KB resource.
# Args: $1 = vector bucket name, $2 = index name
delete_vector_store() {
    local bucket_name="$1"
    local index_name="$2"
    local err rc=0

    echo "Deleting S3 Vectors: ${bucket_name}/${index_name}..."

    # Index first — a bucket that still has indexes will not delete.
    if err=$(aws s3vectors delete-index \
        --vector-bucket-name "${bucket_name}" \
        --index-name "${index_name}" \
        --region "${AWS_REGION}" 2>&1); then
        echo "  ✓ Index deleted"
    elif is_not_found "$err"; then
        echo "  (index already gone)"
    else
        echo "  ⚠️  Failed to delete index ${index_name}: ${err}"
        rc=1
    fi

    if err=$(aws s3vectors delete-vector-bucket \
        --vector-bucket-name "${bucket_name}" \
        --region "${AWS_REGION}" 2>&1); then
        echo "  ✓ Vector bucket deleted"
    elif is_not_found "$err"; then
        echo "  (vector bucket already gone)"
    else
        echo "  ⚠️  Failed to delete vector bucket ${bucket_name}: ${err}"
        rc=1
    fi

    return $rc
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

# Resolve a Knowledge Base ID by its exact name. Fallback for when the SSM
# pointer is absent (e.g. SSM was cleaned first). Echoes the ID, or nothing if
# there is no exact-name match. The AWS CLI auto-paginates before applying
# --query, so this sees every KB in the account.
# Args: $1 = exact KB name
resolve_kb_id_by_name() {
    local kb_name="$1"
    aws bedrock-agent list-knowledge-bases \
        --region "${AWS_REGION}" \
        --query "knowledgeBaseSummaries[?name=='${kb_name}'].knowledgeBaseId | [0]" \
        --output text 2>/dev/null | grep -vx 'None' || true
}

# ── Document Index KB ────────────────────────────────────────────
echo "── Document Index KB ──"
echo ""

DOC_KB_ID=$(ssm_get "kb/document_kb_id" 2>/dev/null || echo "")
if [ -z "$DOC_KB_ID" ] || [ "$DOC_KB_ID" = "None" ]; then
    DOC_KB_ID=$(resolve_kb_id_by_name "${PROJECT_NAME}-document-index-${ENVIRONMENT}")
    [ -n "$DOC_KB_ID" ] && echo "Resolved Document Index KB by name: ${DOC_KB_ID}"
fi

if [ -n "$DOC_KB_ID" ] && [ "$DOC_KB_ID" != "None" ]; then
    delete_knowledge_base "${DOC_KB_ID}" "Document Index KB" || FAILURES=$((FAILURES + 1))
else
    echo "No Document Index KB found (SSM or by name) — nothing to delete"
fi

DOC_VECTOR_BUCKET="${PROJECT_NAME}-document-kb-${ENVIRONMENT}"
delete_vector_store "${DOC_VECTOR_BUCKET}" "bedrock-knowledge-base-default-index" || FAILURES=$((FAILURES + 1))

DOC_ROLE_NAME="${PROJECT_NAME}-document-kb-${ENVIRONMENT}"
delete_iam_role "${DOC_ROLE_NAME}" || FAILURES=$((FAILURES + 1))

echo ""

# ── Standards KB ─────────────────────────────────────────────────
echo "── Standards KB ──"
echo ""

STD_KB_ID=$(ssm_get "kb/standards_kb_id" 2>/dev/null || echo "")
if [ -z "$STD_KB_ID" ] || [ "$STD_KB_ID" = "None" ]; then
    STD_KB_ID=$(resolve_kb_id_by_name "${PROJECT_NAME}-standards-kb-${ENVIRONMENT}")
    [ -n "$STD_KB_ID" ] && echo "Resolved Standards KB by name: ${STD_KB_ID}"
fi

if [ -n "$STD_KB_ID" ] && [ "$STD_KB_ID" != "None" ]; then
    delete_knowledge_base "${STD_KB_ID}" "Standards KB" || FAILURES=$((FAILURES + 1))
else
    echo "No Standards KB found (SSM or by name) — nothing to delete"
fi

STD_VECTOR_BUCKET="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
delete_vector_store "${STD_VECTOR_BUCKET}" "bedrock-knowledge-base-default-index" || FAILURES=$((FAILURES + 1))

STD_ROLE_NAME="${PROJECT_NAME}-standards-kb-${ENVIRONMENT}"
delete_iam_role "${STD_ROLE_NAME}" || FAILURES=$((FAILURES + 1))

# Standards corpus S3 bucket
STD_CORPUS_BUCKET="${PROJECT_NAME}-standards-${ENVIRONMENT}-${AWS_ACCOUNT_ID}"
delete_s3_bucket "${STD_CORPUS_BUCKET}" || FAILURES=$((FAILURES + 1))

echo ""
echo "=================================="
if [ "$FAILURES" -eq 0 ]; then
    echo "Knowledge Base cleanup complete ✓"
    echo "=================================="
else
    echo "❌ Knowledge Base cleanup: ${FAILURES} step(s) failed (see warnings above)."
    echo "   Re-run after resolving, or check 'task verify:clean'."
    echo "=================================="
    exit 1
fi
