#!/bin/bash
# cleanup_legacy_md.sh — Clean up legacy .md files from standards that have
# both a PDF and a markdown version in S3. Keeps the PDF (authoritative source),
# renames the metadata sidecar to match the PDF filename, and deletes the .md.
#
# Also removes the extra owasp-top-10-2025-source.md file.
#
# Usage: bash scripts/utils/cleanup_legacy_md.sh [--dry-run]

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${SCRIPT_DIR}/common.sh"

load_env
require_env
check_aws_credentials

BUCKET_NAME="${PROJECT_NAME}-standards-${ENVIRONMENT}-${AWS_ACCOUNT_ID}"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN — no changes will be made ==="
fi

echo "Bucket: ${BUCKET_NAME}"
echo ""

# Parallel arrays: old sidecar key → new sidecar key (to match PDF filename)
OLD_SIDECARS=(
    "cpg-230/cpg-230.md.metadata.json"
    "cpg-234/cpg-234.md.metadata.json"
    "cps-230/cps-230.md.metadata.json"
    "cps-234/cps-234.md.metadata.json"
    "iso-31000/iso-31000.md.metadata.json"
)
NEW_SIDECARS=(
    "cpg-230/Prudential Practice Guide CPG 230 Operational Risk Management.pdf.metadata.json"
    "cpg-234/cpg_234_information_security_june_2019_1.pdf.metadata.json"
    "cps-230/Prudential Standard CPS 230 Operational Risk Management - clean.pdf.metadata.json"
    "cps-234/cps_234_july_2019_for_public_release.pdf.metadata.json"
    "iso-31000/1580786256_867__AS_2BISO_2B31000-2018_2BRisk_2Bmanagement_2B-_2BGuidelines_2B2001-c030.pdf.metadata.json"
)

# .md files to delete (the legacy conversions)
DELETE_FILES=(
    "cpg-230/cpg-230.md"
    "cpg-234/cpg-234.md"
    "cps-230/cps-230.md"
    "cps-234/cps-234.md"
    "iso-31000/iso-31000.md"
    "owasp-top-10/owasp-top-10-2025-source.md"
)

echo "── Renaming sidecars to match PDF filenames ──"
for i in "${!OLD_SIDECARS[@]}"; do
    old_key="${OLD_SIDECARS[$i]}"
    new_key="${NEW_SIDECARS[$i]}"
    if $DRY_RUN; then
        echo "  [dry-run] Would rename: ${old_key}"
        echo "                      →  ${new_key}"
    else
        if aws s3 cp "s3://${BUCKET_NAME}/${old_key}" "s3://${BUCKET_NAME}/${new_key}" --region "${AWS_REGION}" 2>/dev/null; then
            aws s3 rm "s3://${BUCKET_NAME}/${old_key}" --region "${AWS_REGION}" 2>/dev/null
            echo "  ✓ Renamed: ${old_key}"
            echo "          →  ${new_key}"
        else
            echo "  ⚠ Not found or failed: ${old_key}"
        fi
    fi
done

echo ""
echo "── Deleting legacy .md files ──"
for key in "${DELETE_FILES[@]}"; do
    if $DRY_RUN; then
        echo "  [dry-run] Would delete: ${key}"
    else
        if aws s3 rm "s3://${BUCKET_NAME}/${key}" --region "${AWS_REGION}" 2>/dev/null; then
            echo "  ✓ Deleted: ${key}"
        else
            echo "  ⚠ Not found or failed: ${key}"
        fi
    fi
done

echo ""
echo "Done."
if ! $DRY_RUN; then
    echo ""
    echo "Next steps:"
    echo "  1. Tag remaining standards with jurisdiction/industry via the admin UI"
    echo "  2. Click Sync KB to re-index the knowledge base"
fi
