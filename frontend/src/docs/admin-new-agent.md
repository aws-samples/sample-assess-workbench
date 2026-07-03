# Creating a New Agent

> Admin access required — this guide covers architecture, patterns, and deployment.

## Agent Architecture

Each review domain is implemented as a pair of agents deployed to Amazon Bedrock AgentCore:

| Component | Purpose | Example |
|-----------|---------|---------|
| Review agent | Analyzes documents, returns structured findings | `agents/architecture_review/` |
| Chat agent | Conversational follow-up on findings | `agents/architecture_chat/` |

The review agent receives a document and returns structured JSON findings. The chat agent uses AgentCore Memory to access prior findings and answer questions.

### One shared runtime, configured per domain

You do **not** write Python to add an agent. Every agent runs the same shared runtime — `agents/shared/review_agent.py` and `agents/shared/chat_agent.py` — parameterized by an `AGENT_TYPE` environment variable that selects the agent's entry in the DynamoDB registry. A per-domain agent directory holds only *data*:

| File | Role | Purpose |
|------|------|---------|
| `agent.yaml` | both | Name, role, SSM key, and (review only) the `registry:` block — display metadata, model, tool limits, and the finding schema. |
| `prompt.md` | both | The domain system prompt. |
| `coach_guidance.md` | review only | Quality-judge evaluation criteria. |

There is **no `agent.py`** — the entrypoint is the shared module, copied into the agent directory at deploy time. There is **no committed `requirements.txt`** either — dependencies are shared across all agents and generated at deploy from the `agents` group in the root `pyproject.toml` (see [Dependencies](#dependencies)). The Pydantic model for structured output is built *dynamically* from your declared finding schema by `agents/shared/schema_builder.py` — you describe the fields, the runtime builds the model.

### Data Flow

```
Document → Step Functions → invoke_review_agent → AgentCore Runtime → Agent
                                                                        ↓
Frontend ← DynamoDB ← aggregate_results ← ← ← ← ← ← ← ← ← Structured JSON
```

The frontend renders findings dynamically based on the agent registry — no frontend code changes are needed for new agents that follow the standard patterns.

## Finding Schema Contract

You declare the finding shape as a `finding_schema` block in the review agent's `agent.yaml`. The shared runtime turns that declaration into a Pydantic model at startup.

Every finding automatically gets these **common fields** (added by the runtime — you don't declare them):

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique finding ID (give it an agent prefix in the prompt, e.g. `ARCH-001`, `SEC-001`) |
| `title` | string | Brief, clear title |
| `description` | string | Detailed description (markdown) |
| `recommendation` | string | Specific, actionable recommendation (markdown) |
| `references` | list[str] | References to document sections (optional) |
| `severity` | string | See [Severity](#severity-the-critical-contract) below |

Declare any **domain-specific fields** under `finding_schema.fields`. Each field maps to a Pydantic field; an `enum` list is enforced as a JSON-schema `Literal` (not just prompt guidance):

```yaml
finding_schema:
  severity_levels: [high, medium, low]
  severity_source: direct
  display_strategy: quality_attribute
  fields:
    quality_attribute:
      type: str
      required: true
      description: "ATAM quality attribute: performance, modifiability, ..."
      enum: [performance, modifiability, availability, security, usability]
      display: badge
      color: cyan
```

### Severity: The Critical Contract

The `severity` field drives the entire UI: finding card border colors, severity badges, analytics aggregation, and the risk heatmap. Every finding must end up with a valid lowercase severity value. There are two ways severity gets set, selected by `severity_source` in the schema.

#### Pattern 1: LLM-assigned (`severity_source: direct`)

The LLM assigns severity directly, guided by the prompt. Used by most agents. List the allowed values in `severity_levels`; the runtime makes `severity` a required field whose description enumerates them.

```yaml
finding_schema:
  severity_levels: [critical, high, medium, low]
  severity_source: direct
```

Define what each level means for the domain in `prompt.md`. Appropriate when severity is a subjective judgment call. Agents using this pattern: architecture, security.

#### Pattern 2: Derived (`severity_source: derived`)

Severity is computed from other fields by a declarative matrix — no code. The LLM supplies the inputs; the runtime overwrites `severity` post-parse from the matrix. Used when a formal framework defines severity (e.g. ISO 31000 likelihood × consequence).

```yaml
finding_schema:
  severity_levels: [critical, high, medium, low]
  severity_source: derived
  severity_derivation:
    inputs: [likelihood, consequence]
    matrix:
      "almost_certain,catastrophic": critical
      "likely,major": high
      "possible,moderate": medium
      "rare,insignificant": low
      # ... one entry per combination of the inputs' enum values
  fields:
    likelihood:
      type: str
      required: true
      enum: [almost_certain, likely, possible, unlikely, rare]
      description: "Likelihood rating"
    consequence:
      type: str
      required: true
      enum: [catastrophic, major, moderate, minor, insignificant]
      description: "Consequence rating"
```

Key rules for derived severity:
- The matrix must cover **every** combination of the input fields' enum values. The runtime validates completeness at startup and fails fast with a clear error if any combination is missing — so an incomplete matrix never reaches a review.
- Each input field must declare an `enum`.
- Tell the LLM in the prompt **not** to set severity itself — it's derived and overwritten.

See `agents/risk_review/agent.yaml` for the full ISO 31000 matrix.

#### When to use which

| Scenario | Pattern | Reason |
|----------|---------|--------|
| Severity is a judgment call | `direct` | No formula exists; the LLM's domain expertise decides |
| A standard defines severity from inputs | `derived` | Deterministic = reproducible and auditable |
| Multiple inputs combine into severity | `derived` | Don't ask the LLM to do math it can get wrong |
| Simple high/medium/low scale | `direct` | No added value in a derivation layer |

## Step-by-Step: Adding a New Agent

### 1. Create the agent directories

Create a directory for each of the review and chat agents. They hold config and prompts only — no `agent.py`, no `requirements.txt`:

```
agents/
  my_domain_review/
    agent.yaml          # name, role, ssm_key + registry: block
    prompt.md           # review prompt template
    coach_guidance.md   # quality-judge criteria (optional but recommended)
  my_domain_chat/
    agent.yaml          # name, role, ssm_key (no registry: block)
    prompt.md           # chat prompt template
```

Copy an existing pair (e.g. `architecture_review` / `architecture_chat`) and adapt — it's the fastest way to get the structure right.

### 2. Write the review agent's `agent.yaml`

This is the source of truth for the agent. The deploy and seed scripts discover it by scanning `agents/*/agent.yaml` — no script edits needed.

```yaml
# agents/my_domain_review/agent.yaml
name: my_domain
role: review
ssm_key: agent/my_domain_arn

registry:
  agent_type: my_domain
  display_name: My Domain
  icon: "🔍"
  color: "#9b59b6"
  description: "Reviews documents for my domain concerns. Select for [specific scope]."
  category: technical
  sort_order: 7
  default_depth: ""
  chat_agent: my_domain_chat        # references the chat agent's `name`
  model_id: global.anthropic.claude-sonnet-4-6
  tool_limits:
    search_document: 5
    get_prior_findings: 4
    lookup_standard: 3
  judge_defaults:
    max_iterations: 2
    quality_threshold: 0.7
    coach_enabled: true
  finding_schema:
    severity_levels: [high, medium, low]
    severity_source: direct
    primary_fields: []
    optional_fields: []
    display_strategy: severity_badge
    fields: {}
```

The chat agent's `agent.yaml` is just the three top-level keys (no `registry:` block — it's referenced from the review agent via `chat_agent`):

```yaml
# agents/my_domain_chat/agent.yaml
name: my_domain_chat
role: chat
ssm_key: agent/my_domain_chat_arn
```

**The `description` field is critical** — it's what the AI planner sees when deciding which agents to include in a review. The planner reasons about jurisdiction, industry, and regulatory context, so:
- Generic agents (architecture, security, risk) should have broad descriptions.
- Domain-specific agents should explicitly state their scope: jurisdiction, industry, applicable regulations, and when to select them.
- Example: *"Reviews EU regulatory compliance for financial institutions: GDPR, DORA, EBA outsourcing guidelines, PSD2, US CLOUD Act/Schrems II, data sovereignty, NIS2. Select for EU-regulated banks and financial services institutions."*

You can also edit the description later via the admin **Registry** page without rerunning the seed script.

### 3. Write the prompts

Prompt templates use `$variable` syntax ([Python `string.Template`](https://docs.python.org/3/library/string.html#template-strings)), which is safe with curly braces in prompt content — JSON examples and code blocks won't interfere with substitution.

Review prompts receive:

| Variable | Description |
|----------|-------------|
| `$organizational_context` | Organization-specific context from project settings |
| `$document_content` | The document being reviewed |
| `$current_date` | Today's date (ISO) |

A platform-context boundary is prepended automatically to every review prompt, so you don't need to warn the agent about its own infrastructure.

Chat prompts receive:

| Variable | Description |
|----------|-------------|
| `$organizational_context` | Organization-specific context |
| `$project_name` / `$project_description` / `$project_id` | Project metadata |
| `$findings_section` | Prior findings + available-tools guidance (built by the runtime) |
| `$chat_history` | Previous conversation messages |
| `$question` | The user's current question |
| `$current_date` | Today's date (ISO) |

Structure a review prompt with: domain expertise description, analysis areas, severity-level definitions (for `direct` severity), per-finding instructions, and the placeholder sections at the end:

```markdown
---

Organizational Context:
$organizational_context

---

Analyze this solution design document:

$document_content
```

See `agents/security_review/prompt.md` for a four-level severity example, or `agents/architecture_review/prompt.md` for a three-level example.

### 4. Coach guidance

Coach guidance tells the quality judge what "good" looks like for your domain. Create `coach_guidance.md` in the review agent directory with completeness, specificity, and actionability checks. See `agents/risk_review/coach_guidance.md` for an example.

The seed script reads `coach_guidance.md` automatically and stores it in the registry; you can also update it later via the admin page. Without coach guidance, the quality judge auto-disables coaching for this agent (with a warning) — the review still runs, coaching is just skipped.

### 5. Deploy

```bash
# Deploy the review and chat agents (config generated, deps exported, ARNs written to SSM)
task deploy:agent -- my_domain
task deploy:agent -- my_domain_chat

# Grant the agent execution roles their IAM permissions (registry, memory, guardrails)
task deploy:agent-permissions

# Seed the registry with the new agent metadata
task deploy:seed
```

`deploy:agent` discovers the agent from `agent.yaml`, copies in the shared runtime, exports the pinned `requirements.txt`, runs `agentcore configure` (which generates the `.bedrock_agentcore.yaml` entry — no manual editing), deploys, and writes the agent ARN to SSM. After seeding, the new agent appears automatically in:
- Review plan creation (the planner can select it)
- Plan customize panel (users can add/remove it)
- Project detail tabs (findings display)
- Chat panel (follow-up conversations)
- Analytics dashboard (quality scores)

## Dependencies

Agents share a single dependency set — they all run the same shared runtime — declared as the `agents` dependency group in the root `pyproject.toml` and pinned through `uv.lock`. `deploy_agent.sh` exports that group to a per-agent `requirements.txt` (a gitignored build artifact) at deploy time. To add or bump an agent dependency, edit the `agents` group, run `uv lock`, and redeploy — never hand-edit a generated `requirements.txt`. Pinning through `uv.lock` also keeps the agent dependency surface visible to the weekly vulnerability scan.

## Display Strategies

The frontend renders finding cards based on the `display_strategy` in the agent registry. No frontend changes needed for standard strategies:

| Strategy | When to Use | Example Agent |
|----------|-------------|---------------|
| `severity_badge` | Standard severity (high/medium/low) | default fallback |
| `severity_badge_with_tags` | Severity + reference tags (OWASP, CWE, regulatory) | security, AU FSI compliance |
| `likelihood_consequence` | Risk-style likelihood × consequence | risk |
| `quality_attribute` | Quality attributes + impact types | architecture |

Adding a new display strategy requires a frontend code change in `finding-card.jsx`.
