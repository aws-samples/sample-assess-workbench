#!/bin/bash
# Backup and restore .bedrock_agentcore.yaml to/from S3.
#
# The agentcore CLI stores all deployment state (agent IDs, ARNs, memory IDs,
# execution roles) in a single .bedrock_agentcore.yaml file. This file is not
# version-controlled (it contains account-specific resource IDs) and the CLI
# has no built-in backup or multi-environment support.
#
# This script provides:
#   backup   — push the current config to S3 (with local timestamped copy)
#   restore  — pull the config from S3 for a given environment
#   swap     — safely swap configs during env:switch (backup-before-move)
#
# S3 layout:
#   s3://<terraform-state-bucket>/agentcore-config/<env>/.bedrock_agentcore.yaml
#
# Local backup layout:
#   .bedrock_agentcore/backups/<env>/<timestamp>.yaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load environment
if [ -f "${REPO_ROOT}/.env" ]; then
    set -a
    source "${REPO_ROOT}/.env"
    set +a
fi

AWS_REGION="${AWS_REGION:-us-west-2}"
PROJECT_NAME="${PROJECT_NAME:-risk-assessor}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
CONFIG_FILE="${REPO_ROOT}/.bedrock_agentcore.yaml"
BACKUP_DIR="${REPO_ROOT}/.bedrock_agentcore/backups"

# ── Resolve the Terraform state bucket for the current account ──
resolve_bucket() {
    local account_id
    account_id=$(aws sts get-caller-identity --region "${AWS_REGION}" --query 'Account' --output text 2>/dev/null) || {
        echo "❌ Could not determine AWS account (credentials expired?)" >&2
        return 1
    }
    echo "${PROJECT_NAME}-terraform-state-${account_id}"
}

s3_key() {
    local env="${1:-${ENVIRONMENT}}"
    echo "agentcore-config/${env}/.bedrock_agentcore.yaml"
}

# ── Local timestamped backup ──
local_backup() {
    local env="${1:-${ENVIRONMENT}}"
    local source_file="${2:-${CONFIG_FILE}}"

    if [ ! -f "${source_file}" ]; then
        return 0  # nothing to back up
    fi

    local backup_subdir="${BACKUP_DIR}/${env}"
    mkdir -p "${backup_subdir}"

    local timestamp
    timestamp=$(date '+%Y%m%d-%H%M%S')
    local dest="${backup_subdir}/${timestamp}.yaml"
    cp "${source_file}" "${dest}"
    echo "  ✓ Local backup: ${dest#${REPO_ROOT}/}"

    # Keep only the 10 most recent backups per environment
    local count
    count=$(ls -1 "${backup_subdir}"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
    if [ "${count}" -gt 10 ]; then
        ls -1t "${backup_subdir}"/*.yaml | tail -n +11 | xargs rm -f
    fi
}

# ════════════════════════════════════════════════════════════════
# Commands
# ════════════════════════════════════════════════════════════════

cmd_backup() {
    local env="${1:-${ENVIRONMENT}}"
    echo "Backing up AgentCore config (${env})..."

    if [ ! -f "${CONFIG_FILE}" ]; then
        echo "  ℹ No .bedrock_agentcore.yaml to back up"
        return 0
    fi

    # Local backup first (always works, even without AWS creds)
    local_backup "${env}"

    # S3 backup
    local bucket
    bucket=$(resolve_bucket) || return 1
    local key
    key=$(s3_key "${env}")

    aws s3 cp "${CONFIG_FILE}" "s3://${bucket}/${key}" \
        --region "${AWS_REGION}" \
        --quiet 2>/dev/null && \
        echo "  ✓ S3 backup: s3://${bucket}/${key}" || \
        echo "  ⚠️  S3 backup failed (local backup preserved)"
}

cmd_restore() {
    local env="${1:-${ENVIRONMENT}}"
    echo "Restoring AgentCore config (${env})..."

    local bucket
    bucket=$(resolve_bucket) || return 1
    local key
    key=$(s3_key "${env}")

    # Check if S3 backup exists
    if ! aws s3 ls "s3://${bucket}/${key}" --region "${AWS_REGION}" &>/dev/null; then
        echo "  ℹ No S3 backup found at s3://${bucket}/${key}"

        # Try local backup as fallback
        local backup_subdir="${BACKUP_DIR}/${env}"
        local latest
        latest=$(ls -1t "${backup_subdir}"/*.yaml 2>/dev/null | head -1 || true)
        if [ -n "${latest}" ]; then
            echo "  Found local backup: ${latest#${REPO_ROOT}/}"
            # Back up current file before overwriting
            if [ -f "${CONFIG_FILE}" ]; then
                local_backup "${ENVIRONMENT}" "${CONFIG_FILE}"
            fi
            cp "${latest}" "${CONFIG_FILE}"
            echo "  ✓ Restored from local backup"
            return 0
        fi

        echo "  ❌ No backups found (S3 or local) for environment '${env}'"
        return 1
    fi

    # Back up current file before overwriting
    if [ -f "${CONFIG_FILE}" ]; then
        echo "  Backing up current config before restore..."
        local_backup "${ENVIRONMENT}" "${CONFIG_FILE}"
    fi

    aws s3 cp "s3://${bucket}/${key}" "${CONFIG_FILE}" \
        --region "${AWS_REGION}" \
        --quiet
    echo "  ✓ Restored from s3://${bucket}/${key}"
}

cmd_swap() {
    # Safe swap for env:switch. Takes two args: CURRENT_ENV TARGET_ENV
    #
    # Note: During env:switch, AWS_PROFILE has already been changed to the
    # TARGET environment's profile by the time this runs. This means we can't
    # reliably push to the CURRENT environment's S3 bucket. Local timestamped
    # backups provide the safety net here; S3 backups happen automatically
    # on every deploy:agents / deploy:agent.
    local current="${1:?Usage: agentcore_config.sh swap <current_env> <target_env>}"
    local target="${2:?Usage: agentcore_config.sh swap <current_env> <target_env>}"

    echo "Swapping AgentCore state: ${current} → ${target}"

    # Step 1: Back up the current config locally before touching anything
    if [ -f "${CONFIG_FILE}" ]; then
        local_backup "${current}" "${CONFIG_FILE}"
    fi

    # Step 2: Stash current → .bedrock_agentcore.yaml.<current>
    if [ -f "${CONFIG_FILE}" ]; then
        mv "${CONFIG_FILE}" "${CONFIG_FILE}.${current}"
        echo "  ✓ Stashed current → .bedrock_agentcore.yaml.${current}"
    fi

    # Step 3: Restore target from .bedrock_agentcore.yaml.<target> or S3
    if [ -f "${CONFIG_FILE}.${target}" ]; then
        mv "${CONFIG_FILE}.${target}" "${CONFIG_FILE}"
        echo "  ✓ Restored .bedrock_agentcore.yaml.${target} → .bedrock_agentcore.yaml"
    else
        echo "  ℹ No local .bedrock_agentcore.yaml.${target} found"
        # Try S3 restore from the target account (credentials are already switched)
        local bucket
        bucket=$(resolve_bucket 2>/dev/null) || bucket=""
        if [ -n "${bucket}" ]; then
            local target_key
            target_key=$(s3_key "${target}")
            if aws s3 ls "s3://${bucket}/${target_key}" --region "${AWS_REGION}" &>/dev/null; then
                aws s3 cp "s3://${bucket}/${target_key}" "${CONFIG_FILE}" \
                    --region "${AWS_REGION}" \
                    --quiet 2>/dev/null && \
                    echo "  ✓ Restored ${target} config from S3" || \
                    echo "  ⚠️  S3 restore failed"
            else
                echo "  ℹ No S3 backup for ${target} (first deploy to this environment)"
            fi
        else
            echo "  ℹ No S3 backup available (first deploy to this environment)"
        fi
    fi
}

cmd_list() {
    echo "AgentCore config backups"
    echo ""

    # Local backups
    echo "── Local backups ──"
    if [ -d "${BACKUP_DIR}" ]; then
        for env_dir in "${BACKUP_DIR}"/*/; do
            if [ -d "${env_dir}" ]; then
                local env_name
                env_name=$(basename "${env_dir}")
                local count
                count=$(ls -1 "${env_dir}"*.yaml 2>/dev/null | wc -l | tr -d ' ')
                local latest
                latest=$(ls -1t "${env_dir}"*.yaml 2>/dev/null | head -1 || true)
                if [ -n "${latest}" ]; then
                    local latest_date
                    latest_date=$(basename "${latest}" .yaml)
                    echo "  ${env_name}: ${count} backup(s), latest: ${latest_date}"
                fi
            fi
        done
    else
        echo "  (none)"
    fi
    echo ""

    # S3 backups
    echo "── S3 backups ──"
    local bucket
    bucket=$(resolve_bucket 2>/dev/null) || {
        echo "  (could not check — AWS credentials unavailable)"
        return 0
    }
    local s3_files
    s3_files=$(aws s3 ls "s3://${bucket}/agentcore-config/" --recursive --region "${AWS_REGION}" 2>/dev/null || true)
    if [ -n "${s3_files}" ]; then
        echo "${s3_files}" | while read -r line; do
            echo "  ${line}"
        done
    else
        echo "  (none)"
    fi
}

# ════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════

CMD="${1:-help}"
shift || true

case "${CMD}" in
    backup)  cmd_backup "$@" ;;
    restore) cmd_restore "$@" ;;
    swap)    cmd_swap "$@" ;;
    list)    cmd_list ;;
    help|--help|-h)
        echo "Usage: bash scripts/agentcore_config.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  backup  [env]              Back up current config to S3 + local"
        echo "  restore [env]              Restore config from S3 (or local fallback)"
        echo "  swap    <current> <target>  Safe swap for env:switch"
        echo "  list                        Show available backups"
        echo ""
        echo "Environment defaults to ENVIRONMENT from .env (currently: ${ENVIRONMENT})"
        ;;
    *)
        echo "Unknown command: ${CMD}"
        echo "Run: bash scripts/agentcore_config.sh help"
        exit 1
        ;;
esac
