#!/usr/bin/env bash
# with-env.sh — load .env, then resolve, validate, and account-guard the
# active environment.
#
# SOURCE this (do not execute it) as the SINGLE point of environment resolution
# — at the top of any task command block or script that runs a mutating
# AWS/Terraform operation:
#
#     source scripts/utils/with-env.sh
#
# It loads .env, resolves the target environment, optionally lets a local
# resolver supply per-environment AWS identity, asserts the live AWS account
# matches the declared AWS_ACCOUNT_ID, and exports everything so the commands
# that follow (terraform, aws) act on the right account — or stops loudly with
# `exit 1` so nothing runs against the wrong account. Because it loads .env
# itself, a script that sources this needs no other env loading: do NOT
# `source .env` by hand and do NOT default the tenant knobs (`${ENVIRONMENT:-…}`).
#
# Contract:
#   Loads     .env (set -a, so every value it defines is exported): the tenant
#             knobs (PROJECT_NAME, AWS_REGION, ENVIRONMENT), model IDs,
#             PYTHON_RUNTIME, and AWS_PROFILE / AWS_ACCOUNT_ID for single-account
#             setups.
#   Resolves  a per-command override (a value already set in the environment,
#             e.g. `ENVIRONMENT=demo task …` or `PROJECT_NAME=… AWS_REGION=… task
#             …`) wins over the .env file value, for ENVIRONMENT / PROJECT_NAME /
#             AWS_REGION. There is NO hardcoded "dev" fallback — "dev" is simply
#             the value .env ships with. Empty ENVIRONMENT after the load → loud
#             error.
#   Override  if scripts/utils/with-env.local.sh exists it is sourced after the
#             selector is resolved and may set AWS_PROFILE / AWS_ACCOUNT_ID for
#             the environment (used by multi-account setups). Absent by default;
#             single-account setups take these straight from .env.
#   Guards    when AWS_ACCOUNT_ID is set, the live `aws sts get-caller-identity`
#             account must equal it, else abort. A failed STS call (expired
#             creds) gives a distinct message. No AWS_ACCOUNT_ID → guard not
#             enabled (a visible notice; set AWS_ACCOUNT_ID in .env to enable).
#   Exports   the loaded .env values, AWS_PROFILE (or unsets it), AWS_ACCOUNT_ID,
#             TF_VAR_aws_account_id (so Terraform's allowed_account_ids backstops
#             the same check), ENVIRONMENT, PROJECT_NAME, AWS_REGION, and
#             AWS_DEFAULT_REGION (mirrored from AWS_REGION for botocore).
#
# Filesystem-read-only: it loads .env into the shell and validates, but performs
# no file writes, no sed, no mv; it does not touch the AgentCore symlink or
# frontend/public/config.json — those are derived per-task by the tasks that use
# them. That is what makes it safe to source on every task.

# ── 0. Locate the repo root ───────────────────────────────────────────────
# Walk up from cwd to the directory holding Taskfile.yml. Tasks may run with
# `dir: terraform`, so cwd is not always the repo root, and Task's embedded
# shell does not reliably populate $BASH_SOURCE — the walk-up is interpreter-
# agnostic and resolves repo-relative paths regardless of cwd.
_we_root="$(pwd)"
while [ "${_we_root}" != "/" ] && [ ! -f "${_we_root}/Taskfile.yml" ]; do
  _we_root="$(dirname "${_we_root}")"
done
if [ ! -f "${_we_root}/Taskfile.yml" ]; then
  echo "❌ with-env.sh: could not locate the repo root (no Taskfile.yml at or above $(pwd))." >&2
  exit 1
fi

# ── 1. Load .env (file = base layer; a shell/CLI override wins) ────────────
# This is the single source of truth for environment values. .env supplies the
# tenant knobs (PROJECT_NAME, AWS_REGION, ENVIRONMENT), the model IDs,
# PYTHON_RUNTIME, and — for single-account setups — AWS_PROFILE / AWS_ACCOUNT_ID.
# `set -a` exports everything it defines, so a script that sources this helper
# needs no other env loading.
#
# Precedence: a value already set in the environment — a per-command
# `ENVIRONMENT=demo task …` or `PROJECT_NAME=… AWS_REGION=… task …` — wins over
# the file. Snapshot the overridable knobs, source .env as defaults, then
# restore any that were set. This is the universal "environment beats file"
# rule, and it makes the helper behave identically whether sourced under Task
# (which also dotenv-loads .env) or by a script invoked directly.
if [ -f "${_we_root}/.env" ]; then
  _we_env_ovr="${ENVIRONMENT:-}"
  _we_proj_ovr="${PROJECT_NAME:-}"
  _we_region_ovr="${AWS_REGION:-}"
  set -a
  # shellcheck disable=SC1091
  . "${_we_root}/.env"
  set +a
  [ -n "${_we_env_ovr}" ] && ENVIRONMENT="${_we_env_ovr}"
  [ -n "${_we_proj_ovr}" ] && PROJECT_NAME="${_we_proj_ovr}"
  [ -n "${_we_region_ovr}" ] && AWS_REGION="${_we_region_ovr}"
  unset _we_env_ovr _we_proj_ovr _we_region_ovr
fi

# ── 2. Require the environment selector ────────────────────────────────────
# No "dev" literal — empty after the .env load (and any override) is fatal.
if [ -z "${ENVIRONMENT:-}" ]; then
  echo "❌ No environment selected." >&2
  echo "   Set ENVIRONMENT in .env, or pass it per-command: ENVIRONMENT=<env> task <name>" >&2
  exit 1
fi

# ── 3. Optional local identity resolver ───────────────────────────────────
# Multi-account setups can supply a local resolver that maps $ENVIRONMENT to its
# AWS identity (AWS_PROFILE / AWS_ACCOUNT_ID) and may fail closed on an unknown
# environment. It is sourced into this scope, so it can read $ENVIRONMENT and
# $_we_root and set AWS_PROFILE / AWS_ACCOUNT_ID for the guard below. Absent in
# the single-account default, where those values come straight from .env.
if [ -f "${_we_root}/scripts/utils/with-env.local.sh" ]; then
  # shellcheck disable=SC1091
  . "${_we_root}/scripts/utils/with-env.local.sh"
fi

# ── 4. Account guard — tied to a declared AWS_ACCOUNT_ID ──────────────────
if [ -n "${AWS_ACCOUNT_ID:-}" ]; then
  # Human-readable profile label for messages ("" → default credentials).
  _we_plabel="default credentials"
  [ -n "${AWS_PROFILE:-}" ] && _we_plabel="profile ${AWS_PROFILE}"

  _we_live="$(aws sts get-caller-identity \
    ${AWS_PROFILE:+--profile "${AWS_PROFILE}"} \
    --query Account --output text 2>/dev/null || true)"

  if [ -z "${_we_live}" ] || [ "${_we_live}" = "None" ]; then
    # No/expired credentials — distinct from a wrong-account mismatch.
    echo "❌ Could not read AWS credentials for '${ENVIRONMENT}' (${_we_plabel})." >&2
    echo "   'aws sts get-caller-identity' failed." >&2
    echo "   Refresh your credentials (e.g. 'aws sso login') and retry." >&2
    exit 1
  fi
  if [ "${_we_live}" != "${AWS_ACCOUNT_ID}" ]; then
    echo "❌ Wrong AWS account for '${ENVIRONMENT}'." >&2
    echo "   Expected ${AWS_ACCOUNT_ID} (${_we_plabel}), but the active" >&2
    echo "   credentials resolve to ${_we_live}." >&2
    echo "   Check your AWS credentials (and AWS_PROFILE / AWS_ACCOUNT_ID in .env)." >&2
    exit 1
  fi
else
  echo "ℹ️  No AWS_ACCOUNT_ID set for '${ENVIRONMENT}' — account guard not enabled."
  echo "   Set AWS_ACCOUNT_ID in .env to refuse deploys against the wrong account."
fi

# ── 5. Export the resolved environment ────────────────────────────────────
# AWS_PROFILE: empty → unset (the CLI treats "" as a profile literally named "").
if [ -n "${AWS_PROFILE:-}" ]; then
  export AWS_PROFILE
else
  unset AWS_PROFILE
fi
export ENVIRONMENT
[ -n "${PROJECT_NAME:-}" ] && export PROJECT_NAME
if [ -n "${AWS_REGION:-}" ]; then
  export AWS_REGION
  # botocore (boto3, hence the agentcore toolkit) reads AWS_DEFAULT_REGION — not
  # AWS_REGION — from the environment, then falls back to the profile's
  # configured region. Export both from the one AWS_REGION knob so the aws CLI,
  # botocore, and the runtime containers all resolve the same region.
  export AWS_DEFAULT_REGION="${AWS_REGION}"
fi
if [ -n "${AWS_ACCOUNT_ID:-}" ]; then
  export AWS_ACCOUNT_ID
  export TF_VAR_aws_account_id="${AWS_ACCOUNT_ID}"
fi

# Clean up helper-local scratch vars so they don't leak into the task shell.
unset _we_root _we_live _we_plabel
