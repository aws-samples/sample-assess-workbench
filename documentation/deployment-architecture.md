# Deployment Architecture

How code and configuration get from a developer's laptop into a running
application. This file explains the deploy pipeline structure, the SSM handoff
between the two layers, and which command to run after a given change. For
first-time setup and the step-by-step deploy walkthrough, see
[`SETUP.md`](../SETUP.md) at the repo root. For the convention every
AWS/Terraform script follows to resolve its environment, see
[`deployment-scripts.md`](deployment-scripts.md).

> **Last verified:** 2026-06-24 against `Taskfile.yml`, `scripts/`, and
> `terraform/` (including `terraform/modules/edge/`). Re-verify when adding a
> new deploy step, a new script, or a new cross-stack handoff.

## Two layers, one handoff

The system deploys in two layers that never call each other directly — they
hand off through SSM Parameter Store:

- **AgentCore agents** — deployed via the AgentCore CLI (`scripts/deploy_agent.sh`,
  driven by `task deploy:agent`). On deploy, each agent writes its ARN to SSM.
- **Infrastructure** — deployed via Terraform (`task deploy:infra`). At plan
  time it *reads* the agent ARNs and Knowledge Base IDs from SSM, and at apply
  time it *writes* endpoints and auth URLs back.

The ordering constraint follows from the handoff: agents and Knowledge Bases
must be deployed before infrastructure, or the Terraform plan fails with
"SSM parameter not found". `task deploy` sequences this correctly.

## SSM parameter handoff

All cross-component configuration flows through SSM under
`/{project_name}/{environment}/`:

| Parameter | Written by | Read by |
|-----------|-----------|---------|
| `/agent/*_arn` | `deploy_agent.sh` | Terraform |
| `/memory/shared_memory_arn` | `deploy_shared_memory.sh` | Terraform |
| `/kb/document_kb_id` | `deploy_document_kb.sh` | Terraform |
| `/kb/document_ds_id` | `deploy_document_kb.sh` | Terraform |
| `/kb/standards_kb_id` | `deploy_standards_kb.sh` | Terraform |
| `/infra/api_endpoint` | Terraform | Consumers |
| `/infra/websocket_url` | Terraform | Consumers |
| `/auth/cognito_*` | Terraform | Consumers |
| `/guardrail/id` | Terraform | `deploy_agent.sh`, `grant_agent_permissions.sh` |
| `/guardrail/version` | Terraform | `deploy_agent.sh` |

## Redeployment matrix

Which command to run after a given change. (Run `task --list` for the full set
with descriptions.)

| What changed | Command |
|---|---|
| Agent code (`agents/shared/`) or prompts | `task deploy:agent -- <name>` (or `deploy:agents` for all) |
| Agent dependencies | Edit the `agents` group in `pyproject.toml`, `uv lock`, then redeploy the agent(s) |
| Agent model IDs / registry metadata | `task deploy:seed` |
| Terraform config or `<env>.tfvars` | `task deploy:infra` |
| `load_document` Lambda code | `task build:load-document` then `task deploy:infra` |
| Core shared utilities (`api/core/`) | `task build:core-layer` then `task deploy:infra` |
| Lambda dependency versions (`api/requirements.txt`) | `task build:dependencies-layer` then `task deploy:infra` |
| Standards corpus | `bash scripts/deploy_standards_kb.sh --sync` |
| After any agent redeploy (if execution roles changed) | `task deploy:agent-permissions` |
| Frontend code | `task deploy:frontend` (or `task dev` for the local Vite server) |

## Agent dependency model

Agents do not commit a `requirements.txt`. Every agent runs the same shared
runtime, so they share one dependency set declared as the `agents` dependency
group in the root `pyproject.toml` and pinned through `uv.lock`. At deploy time
`deploy_agent.sh` exports that group to a per-agent `requirements.txt`
(gitignored, a build artifact like `agents/*/shared/`) and hands it to
`agentcore configure --requirements-file`. Pinning through `uv.lock` also means
the weekly dependency scan covers the agent surface. To change an agent
dependency, edit the group, run `uv lock`, and redeploy — never hand-edit a
generated file. See `agents/` and the in-app admin help ("Creating a New Agent")
for the agent-authoring workflow.
