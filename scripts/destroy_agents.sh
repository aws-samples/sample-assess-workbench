#!/usr/bin/env bash
# Delete all AgentCore agents listed in .bedrock_agentcore.yaml, then reconcile
# the CloudWatch log groups the runtime service leaves behind.
#
# `agentcore destroy` also deletes each agent's bound chat memory, so this is the
# single owner of per-agent memory cleanup (destroy_memory.sh handles only the
# standalone shared semantic memory). It does NOT delete the runtime's CloudWatch
# log group (/aws/bedrock-agentcore/runtimes/<id>-*), so those accumulate across
# deploys — this script sweeps them too, matching this project's expected agent
# names (runtimes are not project-namespaced, so a name match is the safe
# selector in a shared account).
#
# Self-guarding: sources with-env.sh, which asserts the live AWS account matches
# the resolved environment. Invoked by `task destroy:agents`.
#
# pipefail (not `set -e`): per-agent destroys and per-group deletes warn and
# continue rather than abort the teardown.

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}" || exit 1

# shellcheck source=scripts/utils/with-env.sh
source scripts/utils/with-env.sh

: "${ENVIRONMENT:?destroy_agents: ENVIRONMENT must be set}"
: "${AWS_REGION:?destroy_agents: AWS_REGION must be set}"

# Re-point at the resolved env so we list/destroy the right env's agents.
bash scripts/agentcore_config.sh link

echo "Deleting AgentCore agents..."

# Read agent names from .bedrock_agentcore.yaml via agentcore configure list
AGENTS=$(agentcore configure list 2>/dev/null | grep '✅' | awk '{print $2}' || true)
if [ -z "$AGENTS" ]; then
  echo "No agents found in .bedrock_agentcore.yaml"
else
  echo "Found agents:"
  echo "$AGENTS"
  echo ""

  for AGENT_NAME in $AGENTS; do
    echo "Deleting ${AGENT_NAME}..."
    agentcore destroy --agent "${AGENT_NAME}" --force 2>&1 || \
      echo "  ⚠️  Could not fully delete ${AGENT_NAME} (may need manual cleanup)"
  done

  echo ""
  echo "✓ Agent cleanup complete"

  # The deployed agents are gone, so remove the local config that tracked them;
  # the next deploy recreates it. .bedrock_agentcore.yaml is a symlink to the
  # canonical .bedrock_agentcore.yaml.<env>: delete both the target and the link
  # so the canonical file is not orphaned behind a dangling link.
  if [ -L .bedrock_agentcore.yaml ]; then
    TARGET=$(readlink .bedrock_agentcore.yaml)
    rm -f "$TARGET" .bedrock_agentcore.yaml
    echo "✓ Removed .bedrock_agentcore.yaml and ${TARGET}"
  elif [ -f .bedrock_agentcore.yaml ]; then
    # Fallback when it is a regular file rather than a symlink.
    rm -f .bedrock_agentcore.yaml
    echo "✓ Removed .bedrock_agentcore.yaml"
  fi
fi

# ── Discover the agent names this repo deploys ────────────────────
# Source of truth for both the account sweep and the log-group reconciliation
# below — always present (read from agents/*/agent.yaml) even when the local
# .bedrock_agentcore.yaml is missing or stale.
expected_agents=$(find agents -name agent.yaml -type f 2>/dev/null | sort \
  | xargs -I{} python3 -c "import yaml,sys; print(yaml.safe_load(open('{}'))['name'])" 2>/dev/null)

# ── Sweep the account for leftover runtimes ───────────────────────
# `agentcore destroy` above drives off the LOCAL config, so it misses runtimes
# that exist in the account but not in this checkout's .bedrock_agentcore.yaml
# (fresh clone, half-failed deploy, lost or region-mismatched config). Runtimes
# are not project/env-namespaced, so match the account's runtimes against the
# names this repo deploys and delete any leftover — the teardown counterpart of
# the verifier's runtime check. Never silent-exit-0 on an orphaned runtime.
echo ""
echo "Sweeping account for leftover AgentCore runtimes..."
if [ -z "$expected_agents" ]; then
  echo "  ⚠️  Could not read expected agent names from agents/*/agent.yaml — skipping sweep"
else
  runtimes=$(aws bedrock-agentcore-control list-agent-runtimes \
    --region "${AWS_REGION}" \
    --query 'agentRuntimes[].[agentRuntimeName,agentRuntimeId]' \
    --output text 2>/dev/null || true)
  swept=0
  while IFS=$'\t' read -r rt_name rt_id; do
    [ -z "$rt_name" ] && continue
    if printf '%s\n' "$expected_agents" | grep -qx "$rt_name"; then
      echo "  Deleting leftover runtime: ${rt_name} (${rt_id})"
      if aws bedrock-agentcore-control delete-agent-runtime \
        --agent-runtime-id "${rt_id}" --region "${AWS_REGION}" >/dev/null 2>&1; then
        swept=$((swept + 1))
      else
        echo "  ⚠️  Could not delete runtime ${rt_name} (${rt_id}) — may need manual cleanup"
      fi
    fi
  done <<< "$runtimes"

  if [ "$swept" -gt 0 ]; then
    echo "✓ ${swept} leftover runtime(s) swept"
  else
    echo "  No leftover runtimes matching this project's agents"
  fi
fi

# ── Reconcile runtime log groups ──────────────────────────────────
# The runtime service auto-creates /aws/bedrock-agentcore/runtimes/<id>-<endpoint>
# per runtime and `agentcore destroy` leaves it behind, so they pile up across
# redeploys. Sweep groups belonging to this project's agents — matched on the
# agent name plus a trailing hyphen (so 'architect-' never catches
# 'architect_chat-'). Runs unconditionally so pre-existing orphans are cleaned.
echo ""
echo "Reconciling AgentCore runtime log groups..."
if [ -z "$expected_agents" ]; then
  echo "  ⚠️  Could not read expected agent names from agents/*/agent.yaml — skipping"
else
  log_groups=$(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/" \
    --query "logGroups[].logGroupName" \
    --output text --region "${AWS_REGION}" 2>/dev/null | tr '\t' '\n' || true)

  removed=0
  for lg in $log_groups; do
    rest=${lg#/aws/bedrock-agentcore/runtimes/}
    for agent in $expected_agents; do
      case "$rest" in
        "${agent}-"*)
          echo "  Deleting log group: ${lg}"
          if aws logs delete-log-group --log-group-name "$lg" --region "${AWS_REGION}" 2>/dev/null; then
            removed=$((removed + 1))
          else
            echo "  ⚠️  Could not delete ${lg}"
          fi
          break
          ;;
      esac
    done
  done

  if [ "$removed" -gt 0 ]; then
    echo "✓ ${removed} runtime log group(s) removed"
  else
    echo "  No matching runtime log groups found"
  fi
fi
