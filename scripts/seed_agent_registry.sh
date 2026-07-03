#!/bin/bash
# Seed the agent registry in DynamoDB from agent.yaml files.
# Idempotent — safe to re-run (uses put-item which overwrites).
#
# Discovers all agents by scanning agents/*/agent.yaml:
# - Review agents (with a "registry:" block) get full registry entries
#   including finding_schema, coach_guidance, display metadata.
# - Chat agents (role: chat, no registry block) get lightweight entries
#   with just the prompt template — enough for the generic chat runtime.
#
# To add a new agent: create the directory with agent.yaml, prompt.md,
# and requirements.txt. Then run: task deploy:seed

set -e

source "$(dirname "$0")/common.sh"

SCRIPT_DIR="$(dirname "$0")"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=================================="
echo "Seed Agent Registry"
echo "=================================="
echo ""

load_env
require_env

TABLE_NAME=$(ssm_get "dynamodb-table" 2>/dev/null || echo "${PROJECT_NAME}-projects-${ENVIRONMENT}")
SSM_PREFIX="/${PROJECT_NAME}/${ENVIRONMENT}"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "Table: ${TABLE_NAME}"
echo "SSM prefix: ${SSM_PREFIX}"
echo "Region: ${AWS_REGION}"
echo ""

# Resolve a chat agent's SSM key by finding its agent.yaml
resolve_chat_ssm() {
    local chat_name="$1"
    local yaml_file
    yaml_file=$(python3 -c "
import yaml, glob, sys
for f in sorted(glob.glob('${REPO_ROOT}/agents/*/agent.yaml')):
    with open(f) as fh:
        cfg = yaml.safe_load(fh)
    if cfg.get('name') == sys.argv[1]:
        print(f)
        break
" "${chat_name}" 2>/dev/null)

    if [ -z "$yaml_file" ]; then
        echo ""
        return
    fi

    local ssm_key
    ssm_key=$(python3 -c "
import yaml, sys
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f)
print(cfg.get('ssm_key', ''))
" "${yaml_file}")

    echo "${SSM_PREFIX}/${ssm_key}"
}

# Process a single review agent's agent.yaml and write to DynamoDB
seed_agent() {
    local yaml_file="$1"
    local agent_dir
    agent_dir=$(dirname "$yaml_file")

    # Parse the full agent.yaml including registry block.
    # Use `|| true` to prevent set -e from aborting when python exits
    # non-zero for agent.yaml files without a registry block.
    local agent_json
    agent_json=$(python3 -c "
import yaml, json, sys
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f)
reg = cfg.get('registry')
if not reg:
    sys.exit(0)  # no registry — not an error, just nothing to print
out = {
    'name': cfg['name'],
    'ssm_key': cfg['ssm_key'],
    'agent_type': reg['agent_type'],
    'display_name': reg['display_name'],
    'icon': reg['icon'],
    'color': reg['color'],
    'description': reg['description'],
    'category': reg['category'],
    'sort_order': str(reg['sort_order']),
    'default_depth': reg.get('default_depth', ''),
    'chat_agent': reg.get('chat_agent', ''),
    'model_id': reg.get('model_id', ''),
    'finding_schema': json.dumps(reg['finding_schema']),
    'tool_limits': json.dumps(reg.get('tool_limits', {})),
    'judge_defaults': json.dumps(reg.get('judge_defaults', {})),
}
print(json.dumps(out))
" "${yaml_file}" 2>/dev/null) || true

    if [ -z "$agent_json" ]; then
        return  # No registry block — skip (chat agents, etc.)
    fi

    # Extract fields
    local agent_type display_name chat_agent_name
    agent_type=$(echo "$agent_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['agent_type'])")
    display_name=$(echo "$agent_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['display_name'])")
    chat_agent_name=$(echo "$agent_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['chat_agent'])")

    # Read prompt template
    local prompt_template=""
    if [ -f "${agent_dir}/prompt.md" ]; then
        prompt_template=$(cat "${agent_dir}/prompt.md")
    else
        echo "  ⚠️  No prompt.md found in ${agent_dir}"
    fi

    # Read coach guidance (optional)
    local coach_guidance=""
    if [ -f "${agent_dir}/coach_guidance.md" ]; then
        coach_guidance=$(cat "${agent_dir}/coach_guidance.md")
    fi

    # Resolve SSM paths
    local review_ssm
    review_ssm="${SSM_PREFIX}/$(echo "$agent_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['ssm_key'])")"
    local chat_ssm=""
    if [ -n "$chat_agent_name" ]; then
        chat_ssm=$(resolve_chat_ssm "$chat_agent_name")
    fi

    # Build DynamoDB item and write.
    # Use temp files for large text fields (prompt, coach guidance) to
    # avoid shell ARG_MAX limits on command-line arguments.
    local tmpdir
    tmpdir=$(mktemp -d)
    echo -n "${prompt_template}" > "${tmpdir}/prompt"
    echo -n "${coach_guidance}" > "${tmpdir}/coach"

    local ITEM
    ITEM=$(python3 -c "
import json, sys, pathlib

agent = json.loads(sys.argv[1])
review_ssm = sys.argv[2]
chat_ssm = sys.argv[3]
timestamp = sys.argv[4]
tmpdir = sys.argv[5]

prompt_template = pathlib.Path(tmpdir, 'prompt').read_text()
coach_guidance = pathlib.Path(tmpdir, 'coach').read_text()

item = {
    'PK':{'S':'AGENT_REGISTRY'},
    'SK':{'S':'AGENT#'+agent['agent_type']},
    'agent_type':{'S':agent['agent_type']},
    'display_name':{'S':agent['display_name']},
    'icon':{'S':agent['icon']},
    'color':{'S':agent['color']},
    'description':{'S':agent['description']},
    'category':{'S':agent['category']},
    'has_review_agent':{'BOOL':True},
    'has_chat_agent':{'BOOL':bool(chat_ssm)},
    'has_judge_agent':{'BOOL':False},
    'review_agent_ssm_param':{'S':review_ssm},
    'chat_agent':{'S':agent['chat_agent']},
    'chat_agent_ssm_param':{'S':chat_ssm},
    'judge_agent_ssm_param':{'S':''},
    'enabled':{'BOOL':True},
    'sort_order':{'N':agent['sort_order']},
    'finding_schema':{'S':agent['finding_schema']},
    'tool_limits':{'S':agent['tool_limits']},
    'judge_defaults':{'S':agent['judge_defaults']},
    'model_id':{'S':agent['model_id']},
    'prompt_template':{'S':prompt_template},
    'default_depth':{'S':agent['default_depth']},
    'coach_guidance':{'S':coach_guidance},
    'created_at':{'S':timestamp},
}
print(json.dumps(item))
" "${agent_json}" "${review_ssm}" "${chat_ssm}" "${TIMESTAMP}" "${tmpdir}")

    rm -rf "${tmpdir}"

    aws dynamodb put-item \
        --table-name "${TABLE_NAME}" \
        --region "${AWS_REGION}" \
        --item "${ITEM}" > /dev/null 2>&1

    echo "  ✓ ${agent_type} (${display_name})"
}

# Process a single chat agent's agent.yaml and write to DynamoDB.
# Chat agents get a lightweight registry entry — just enough for the
# generic chat runtime to load its prompt template at startup.
seed_chat_agent() {
    local yaml_file="$1"
    local agent_dir
    agent_dir=$(dirname "$yaml_file")

    # Parse agent.yaml — chat agents have no registry block, just name/role/ssm_key/model_id
    local agent_name agent_role agent_model_id agent_tool_limits
    eval "$(python3 -c "
import yaml, sys
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f)
print(f'agent_name=\"{cfg[\"name\"]}\"')
print(f'agent_role=\"{cfg[\"role\"]}\"')
print(f'agent_model_id=\"{cfg.get(\"model_id\", \"\")}\"')
import json
print(f'agent_tool_limits={json.dumps(json.dumps(cfg.get(\"tool_limits\", {})))}')
" "${yaml_file}" 2>/dev/null)" || true

    # Only process chat agents
    if [ "$agent_role" != "chat" ]; then
        return
    fi

    # Read prompt template
    local prompt_template=""
    if [ -f "${agent_dir}/prompt.md" ]; then
        prompt_template=$(cat "${agent_dir}/prompt.md")
    else
        echo "  ⚠️  No prompt.md found in ${agent_dir}"
        return
    fi

    # Build DynamoDB item and write.
    local tmpdir
    tmpdir=$(mktemp -d)
    echo -n "${prompt_template}" > "${tmpdir}/prompt"

    local ITEM
    ITEM=$(python3 -c "
import json, sys, pathlib

agent_name = sys.argv[1]
timestamp = sys.argv[2]
tmpdir = sys.argv[3]
model_id = sys.argv[4]
tool_limits = sys.argv[5]

prompt_template = pathlib.Path(tmpdir, 'prompt').read_text()

item = {
    'PK':{'S':'AGENT_REGISTRY'},
    'SK':{'S':'AGENT#'+agent_name},
    'agent_type':{'S':agent_name},
    'role':{'S':'chat'},
    'model_id':{'S':model_id},
    'tool_limits':{'S':tool_limits},
    'prompt_template':{'S':prompt_template},
    'created_at':{'S':timestamp},
}
print(json.dumps(item))
" "${agent_name}" "${TIMESTAMP}" "${tmpdir}" "${agent_model_id}" "${agent_tool_limits}")

    rm -rf "${tmpdir}"

    aws dynamodb put-item \
        --table-name "${TABLE_NAME}" \
        --region "${AWS_REGION}" \
        --item "${ITEM}" > /dev/null 2>&1

    echo "  ✓ ${agent_name} (chat)"
}

# ── Main: discover and seed all agents ─────────────────────────────
echo "Discovering agents..."
echo ""

echo "Review agents:"
AGENT_COUNT=0
for yaml_file in $(find "${REPO_ROOT}/agents" -name "agent.yaml" -type f | sort); do
    seed_agent "$yaml_file"
    AGENT_COUNT=$((AGENT_COUNT + 1))
done

echo ""
echo "Chat agents:"
for yaml_file in $(find "${REPO_ROOT}/agents" -name "agent.yaml" -type f | sort); do
    seed_chat_agent "$yaml_file"
done

if [ "$AGENT_COUNT" -eq 0 ]; then
    echo "❌ No agent.yaml files found in agents/*/"
    exit 1
fi

echo ""
echo "=================================="
echo "Agent registry seeded ✓"
echo "=================================="
