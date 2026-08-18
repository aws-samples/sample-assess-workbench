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
#   link     — re-point the .bedrock_agentcore.yaml symlink at an env's
#              canonical .bedrock_agentcore.yaml.<env> file
#
# S3 layout:
#   s3://<terraform-state-bucket>/agentcore-config/<env>/.bedrock_agentcore.yaml
#
# Local backup layout:
#   .bedrock_agentcore/backups/<env>/<timestamp>.yaml

# Backups are timestamp-named (YYYYMMDD-HHMMSS.yaml): listing them with `ls`
# is safe (no whitespace in names, lexical order == chronological order) and
# `ls -t` mtime sorting has no clean `find` equivalent. SC2012 disabled file-wide.
# shellcheck disable=SC2012

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Resolve the environment via the single source of truth: loads .env (a
# per-command override wins over the file) and account-guards. Never source
# .env by hand here. See scripts/utils/with-env.sh.
# shellcheck source=scripts/utils/with-env.sh
source "${SCRIPT_DIR}/utils/with-env.sh"

: "${AWS_REGION:?AWS_REGION must be set (see .env.example)}"
: "${PROJECT_NAME:?PROJECT_NAME must be set (see .env.example)}"
: "${ENVIRONMENT:?ENVIRONMENT must be set (see .env.example)}"
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
    echo "  ✓ Local backup: ${dest#"${REPO_ROOT}"/}"

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
            echo "  Found local backup: ${latest#"${REPO_ROOT}"/}"
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

cmd_link() {
    # Re-point .bedrock_agentcore.yaml → .bedrock_agentcore.yaml.<env> for the
    # resolved environment. The agentcore CLI writes *through* the symlink into
    # the canonical per-env file, so switching environments never clobbers state.
    # Per-invocation and derived from $ENVIRONMENT. Tasks call this at the top of
    # their command block before any agentcore CLI command so the live config
    # reflects the env the command runs as.
    local env="${1:-${ENVIRONMENT}}"
    local target=".bedrock_agentcore.yaml.${env}"

    # Safety guard: .bedrock_agentcore.yaml must be a symlink. A regular file
    # here means the canonical per-env files are not established yet — refuse
    # loudly rather than overwrite a live config and lose AgentCore state.
    if [ -e "${CONFIG_FILE}" ] && [ ! -L "${CONFIG_FILE}" ]; then
        echo "❌ ${CONFIG_FILE#"${REPO_ROOT}"/} is a regular file, not a symlink." >&2
        echo "   Refusing to replace it — that would risk losing live AgentCore state." >&2
        echo "   Move it to .bedrock_agentcore.yaml.${env}, then re-run." >&2
        return 1
    fi

    # ln -sfn atomically replaces an existing symlink; the relative target keeps
    # the link portable across clones/paths. A dangling target (first deploy to
    # a new env) is fine — the CLI's open(path, "w") creates the file through it.
    ln -sfn "${target}" "${CONFIG_FILE}"
    echo "  ✓ .bedrock_agentcore.yaml → ${target}"
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
    link)    cmd_link "$@" ;;
    list)    cmd_list ;;
    help|--help|-h)
        echo "Usage: bash scripts/agentcore_config.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  backup  [env]              Back up current config to S3 + local"
        echo "  restore [env]              Restore config from S3 (or local fallback)"
        echo "  link    [env]               Re-point .bedrock_agentcore.yaml symlink at <env>"
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
