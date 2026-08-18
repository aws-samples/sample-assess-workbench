# Solution Design Review Application — System Overview

An AI-powered application that reviews solution design documents using specialized agents for architecture, security, risk, and automotive compliance assessment. An adaptive workflow powered by an AI planner analyzes each document and produces a custom review plan — selecting agents, grouping them, and setting focus areas — before execution.

This is the narrative system reference. For visual diagrams see:
- [architecture-overview.md](architecture-overview.md) — logical components
- [aws-services.md](aws-services.md) — AWS resources
- [security-architecture.md](security-architecture.md) — trust boundaries and authN/authZ
- [data-model.md](data-model.md) — DynamoDB + S3 layout
- [deployment-architecture.md](deployment-architecture.md) — how pipelines fit together

## Component Details

### 1. API Layer (HTTP API v2)

Single Lambda handler behind API Gateway HTTP API v2 with JWT authorizer.

**Endpoints:**
- `POST /projects` — Create project with pre-signed S3 upload URLs (multi-file)
- `GET /projects` — List all projects
- `GET /projects/{id}` — Get project details (includes review results)
- `DELETE /projects/{id}` — Delete project, reviews, chat history, and S3 documents
- `POST /projects/{id}/review` — Trigger async review (returns 202 Accepted)
- `GET /projects/{id}/document` — Get document content from S3
- `POST /projects/{id}/plan/approve` — Approve or modify AI-generated review plan
- `POST /contexts` — Create context document with pre-signed upload URL
- `GET /contexts` — List all context documents
- `GET /contexts/{id}` — Get context metadata
- `DELETE /contexts/{id}` — Delete context and S3 file
- `GET /contexts/{id}/content` — Get context markdown content
- `PUT /contexts/{id}/content` — Update context markdown content
- `GET /agents` — Get agent registry (dynamic agent metadata)
- `GET /health` — Health check (unauthenticated)

See [../api/openapi.yaml](../api/openapi.yaml) for the full OpenAPI specification.

### 2. Adaptive Review Workflow (Step Functions)

The review workflow uses an AI planner to produce document-specific review plans. See [adaptive-workflow-design.md](../.design_specs/done/adaptive-workflow-design.md) for the full design spec.

**Workflow steps:**

1. **LoadDocument** — Reads files from S3, extracts text from PDFs (PyMuPDF), runs two-pass image analysis on diagrams (triage + deep analysis via Bedrock Converse). See [image-analysis-design.md](../.design_specs/done/image-analysis-design.md).
2. **PlanReview** — AI planner (Bedrock Converse with toolUse) analyzes the document and produces a review plan: which agents to invoke, grouping (parallel/sequential), focus areas, depth level.
3. **StorePlan** — Stores the plan in DynamoDB and pauses execution using the Step Functions callback pattern. Frontend displays the plan for user review and customization.
4. **ExecuteGroups** — Nested Map state: iterates over sequential groups, with agents within each group running in parallel. Each agent is invoked via AgentCore Runtime.
5. **AggregateResults** — Combines findings from all agents, computes statistics, stores results in DynamoDB, and writes findings to shared semantic memory.

**Real-time progress:** Each workflow Lambda emits WebSocket events (`review_progress`) back to the browser for live visualization.

### 3. Data Layer

A single DynamoDB table holds projects, reviews, plans, chat history, progress events, feedback, contexts, and the agent registry using a `PK`/`SK` single-table design with two GSIs. A separate connections table tracks live WebSockets with TTL cleanup. User-uploaded documents and workflow artifacts live in one S3 bucket; the SPA is served from a second S3 bucket behind CloudFront.

For the full entity list, access patterns, and S3 layout, see [data-model.md](data-model.md).

### 4. Agent Architecture

#### Dynamic Agent Registry

Agents are registered in DynamoDB (`AGENT_REGISTRY` partition). The planner, review invoker, chat handler, and frontend all read from this registry — no hardcoded agent lists. Adding a new agent type requires a registry entry and deployed agent code, no Lambda or frontend changes.

#### Review Agents

Each review agent analyzes documents and produces structured findings via Pydantic models:

- **Architecture** — design patterns, scalability, performance, maintainability
- **Security** — vulnerabilities, authentication, data protection, compliance
- **Risk** — technical risks, operational risks, dependencies, disaster recovery
- **Automotive Compliance** — FMVSS, ISO 26262, ISO/SAE 21434, SOTIF, emissions, data privacy

Agents are deployed to AgentCore Runtime with `--disable-memory`. They receive `document_content` and `organizational_context` in their payload and return structured JSON (findings array + summary).

#### Chat Agents

Conversational agents for interactive Q&A about review findings. Each domain has a chat variant that:

- Receives the user's question, project context, and shared memory ID
- Calls `retrieve_memory_records` via boto3 (semantic search scoped to project + domain)
- Injects relevant findings into the prompt as context
- Streams responses token-by-token via AgentCore SSE → WebSocket relay
- Loads last 10 conversation turns from DynamoDB for multi-turn continuity

Chat agents use `model_id` from the DynamoDB agent registry (set via `agent.yaml` and seeded by `task deploy:seed`).

#### Memory Architecture

**Shared SEMANTIC Memory** — vector-based store for all review findings.

- Written by `aggregate_results` Lambda after each review (`batch_create_memory_records`)
- Read by chat agents via `retrieve_memory_records` (direct boto3, not session manager)
- Namespaced: `/findings/{project_id}/{agent_type}`
- Event expiry: 90 days

Direct boto3 is used instead of `AgentCoreMemorySessionManager` because:
1. Memory is externally populated (by the review workflow, not by chat agents)
2. Avoids mixing chat conversations with review findings in the search index
3. Gives explicit control over namespace scoping and result formatting

#### Organizational Context Documents

Context documents describe business environment, regulatory requirements, and technology standards. They are loaded from S3 and passed to all agents (review + chat) via `{organizational_context}` placeholder in prompts.

#### Prompt Architecture

All prompts are externalized to markdown files with `{placeholder}` templating:

```
agents/{domain}_{role}/
├── agent.py          # Agent entrypoint
├── prompt.md         # Prompt template
└── requirements.txt  # Dependencies
```

Edit `.md` files to change agent behavior, then redeploy with `task deploy:agent -- <name>`.

### 5. Frontend

Preact + Vite single-page application. Key features:

- Multi-file drag-and-drop upload with parallel pre-signed URL uploads
- Plan preview and customization panel (modify agents, groups, focus areas before execution)
- Live review visualization (animated agent graph driven by WebSocket events)
- Split-panel project detail (findings left, chat right, draggable resize)
- Real-time chat with markdown rendering and streaming
- Dynamic agent tabs and metadata from registry
- i18n framework (English + Spanish) with locale switcher
- Canvas-based risk heatmap
- Cognito auth via `AuthProvider` context

Runtime config loaded from `config.json` (generated by Terraform, gitignored).

### 6. Authentication

All HTTP API routes except `/health` are protected by Cognito JWT authorizers. The WebSocket API validates the Cognito ID token on `$connect` via a custom Lambda authorizer. The frontend uses Cognito Hosted UI with the OAuth authorization code flow.

For trust boundaries, authZ model, and IAM role scoping, see [security-architecture.md](security-architecture.md).

### 7. Infrastructure

Modular Terraform in `terraform/` with modules for `api`, `auth`, `data`, `edge`, `memory`, `monitoring`, `ssm`, `storage`, `websocket`, `workflow`, and each of the two Knowledge Bases. The `edge` module (S3 + CloudFront + WAF + API/WebSocket proxy) is optional in dev, controlled by `deploy_frontend` and `enable_api_proxy` variables. In staging/prod, the edge module is the single entry point for all browser traffic — SPA, REST API, and WebSocket — with WAF and origin lockdown protecting all paths.

Cross-component wiring flows through SSM Parameter Store: AgentCore deploy scripts write agent ARNs; Knowledge Base scripts write KB/data-source IDs; Terraform reads them at plan time and writes endpoints + auth URLs back. Deployment is orchestrated by `Taskfile.yml`.

For the full pipeline structure, the SSM handoff, and the redeployment matrix, see [deployment-architecture.md](deployment-architecture.md). For first-time setup and deployment, see [../SETUP.md](../SETUP.md).

### 8. Cost Estimates (per review)

| Component | Cost |
|-----------|------|
| API Gateway | ~$0.000001 |
| Lambda | ~$0.0001–0.0005 |
| DynamoDB | ~$0.00001 |
| Step Functions | ~$0.0001 |
| Bedrock (Claude) | ~$0.10–0.50 |
| **Total** | **~$0.10–0.50** |

### 9. Security

See [security-architecture.md](security-architecture.md) for the full security posture — trust boundaries, authN/authZ, WAF coverage, IAM role scoping, data protection, and known gaps. [`.design_specs/done/security-review.md`](../.design_specs/done/security-review.md) contains the detailed findings-level analysis.

## Documentation

- [architecture-overview.md](architecture-overview.md) — High-level component diagram
- [aws-services.md](aws-services.md) — AWS resource diagram
- [security-architecture.md](security-architecture.md) — Trust boundaries, authN/authZ, encryption
- [data-model.md](data-model.md) — DynamoDB + S3 layout
- [deployment-architecture.md](deployment-architecture.md) — How deploy pipelines fit together, SSM handoff, redeployment matrix
- [../SETUP.md](../SETUP.md) — Setup & deployment guide
- [../api/openapi.yaml](../api/openapi.yaml) — OpenAPI specification
- [../.design_specs/](../.design_specs/) — Active design and implementation specs
- [../.design_specs/done/](../.design_specs/done/) — Completed design docs (includes adaptive workflow, image analysis, WebSocket chat, security review)
