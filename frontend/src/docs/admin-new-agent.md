# Creating a New Agent

> Admin access required — this guide covers architecture, patterns, and deployment.

## Agent Architecture

Each review domain is implemented as a pair of agents deployed to Amazon Bedrock AgentCore:

| Component | Purpose | Example |
|-----------|---------|---------|
| Review agent | Analyzes documents, returns structured findings | `agents/architecture_review/` |
| Chat agent | Conversational follow-up on findings | `agents/architecture_chat/` |

The review agent receives a document and returns structured JSON findings via Pydantic models. The chat agent uses AgentCore Memory to access prior findings and answer questions.

### Data Flow

```
Document → Step Functions → invoke_review_agent → AgentCore Runtime → Agent
                                                                        ↓
Frontend ← DynamoDB ← aggregate_results ← ← ← ← ← ← ← ← ← Structured JSON
```

The frontend renders findings dynamically based on the agent registry — no frontend code changes are needed for new agents that follow the standard patterns.

## Finding Schema Contract

Every agent must return findings with these required fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique ID with agent prefix (e.g., `ARCH-001`, `SEC-001`) |
| `severity` | string | One of: `critical`, `high`, `medium`, `low` |
| `title` | string | Brief, clear title |
| `description` | string | Detailed description |
| `recommendation` | string | Specific, actionable recommendation |
| `references` | list[str] | References to document sections (optional) |

Additional domain-specific fields can be added freely — the frontend renders them via display strategies configured in the agent registry.

### Severity: The Critical Contract

The `severity` field drives the entire UI: finding card border colors, severity badges, analytics aggregation, and the risk heatmap. Every finding must have a valid lowercase severity value.

There are two patterns for how severity gets set:

#### Pattern 1: LLM-Assigned Severity (Default)

The LLM decides severity directly based on prompt guidance. Used by most agents.

```python
class MyFinding(BaseModel):
    id: str = Field(description="Unique finding ID (e.g., MY-001)")
    severity: str = Field(description="Severity level: critical, high, medium, or low")
    # ... other fields
```

The prompt defines what each severity level means for the domain, and the LLM assigns it. This is appropriate when severity is a subjective judgment call.

Agents using this pattern: architecture, security, automotive compliance.

#### Pattern 2: Derived Severity (Deterministic)

Severity is computed from other fields using a deterministic formula. The LLM provides the inputs, code derives the output. Used when a formal framework defines severity.

```python
from pydantic import model_validator

class RiskFinding(BaseModel):
    likelihood: str = Field(description="Likelihood: almost_certain, likely, possible, unlikely, rare")
    consequence: str = Field(description="Consequence: catastrophic, major, moderate, minor, insignificant")
    severity: str = Field(default="", description="Derived from likelihood × consequence matrix")
    # ... other fields

    @model_validator(mode="after")
    def derive_severity(self):
        """Always derive severity from the risk matrix, overriding any LLM value."""
        self.severity = RISK_MATRIX.get(
            (self.likelihood, self.consequence), "medium"
        )
        return self
```

Key rules for derived severity:
- Use `model_validator(mode="after")`, not `field_validator(mode="before")`. Field validators don't fire when the LLM omits a field with a default value.
- Always overwrite — don't conditionally check `if v`. The derivation is the source of truth.
- The prompt should tell the LLM not to set severity itself.
- Provide a sensible fallback (e.g., `"medium"`) for unrecognized input combinations.

Agents using this pattern: risk (ISO 31000 likelihood × consequence matrix).

#### When to Use Which Pattern

| Scenario | Pattern | Reason |
|----------|---------|--------|
| Severity is a judgment call | LLM-assigned | No formula exists; the LLM's domain expertise decides |
| A standard defines severity from inputs | Derived | Deterministic = reproducible and auditable |
| Multiple inputs combine into severity | Derived | Don't ask the LLM to do math it can get wrong |
| Simple high/medium/low scale | LLM-assigned | No added value in a derivation layer |


## Step-by-Step: Adding a New Agent

### 1. Create the Review Agent

Create a directory under `agents/`:

```
agents/
  my_domain_review/
    agent.py          # AgentCore entrypoint + Pydantic model
    prompt.md         # Review prompt template
    coach_guidance.md # Quality judge evaluation criteria (optional)
    requirements.txt  # Python dependencies
```

#### agent.py

```python
"""My domain review agent implementation."""

import os
from string import Template
from botocore.config import Config as BotocoreConfig
from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from pydantic import BaseModel, Field
from typing import List
from pathlib import Path

app = BedrockAgentCoreApp()


class MyFinding(BaseModel):
    """A single finding for my domain."""
    id: str = Field(description="Unique finding ID (e.g., MY-001)")
    severity: str = Field(description="Severity level: critical, high, medium, or low")
    title: str = Field(description="Brief, clear title")
    description: str = Field(description="Detailed description")
    recommendation: str = Field(description="Specific, actionable recommendation")
    references: List[str] = Field(default_factory=list, description="Document references")
    # Add domain-specific fields here


class MyReview(BaseModel):
    """Review results with structured findings."""
    findings: List[MyFinding] = Field(description="List of findings")
    summary: str = Field(description="Overall assessment")


@app.entrypoint
def invoke(payload):
    """AgentCore entrypoint."""
    if "document_content" not in payload:
        return {"error": "Payload must contain 'document_content'"}

    agent = Agent(
        model=BedrockModel(
            model_id=os.environ["MODEL_ID"],
            boto_client_config=BotocoreConfig(read_timeout=600),
        ),
        structured_output_model=MyReview,
    )

    prompt = Template((Path(__file__).parent / "prompt.md").read_text()).safe_substitute(
        organizational_context=payload.get("organizational_context", ""),
        document_content=payload["document_content"],
    )

    result = agent(prompt)

    if result.structured_output:
        output = result.structured_output.model_dump()
        output["metrics"] = _extract_metrics(result)
        return output
    return {"error": "Failed to get structured output"}


def _extract_metrics(result):
    """Extract observability metrics from AgentResult."""
    metrics = {}
    try:
        m = result.metrics
        usage = m.accumulated_usage or {}
        metrics["input_tokens"] = usage.get("inputTokens", 0)
        metrics["output_tokens"] = usage.get("outputTokens", 0)
        metrics["total_tokens"] = usage.get("totalTokens", 0)
        metrics["cache_read_tokens"] = usage.get("cacheReadInputTokens", 0)
        metrics["cache_write_tokens"] = usage.get("cacheWriteInputTokens", 0)
        metrics["cycle_count"] = len(m.cycle_durations) if m.cycle_durations else 0
        metrics["total_duration_s"] = round(sum(m.cycle_durations), 2) if m.cycle_durations else 0
        latency = (m.accumulated_metrics or {}).get("latencyMs", 0)
        metrics["model_latency_ms"] = latency
    except Exception as e:
        metrics["_error"] = str(e)
    return metrics


if __name__ == "__main__":
    app.run()
```

#### prompt.md

The prompt template uses `$variable` syntax ([Python string.Template](https://docs.python.org/3/library/string.html#template-strings)) for placeholder substitution. This is safe with curly braces in prompt content — JSON examples, code blocks, and markdown formatting won't interfere with variable substitution.

Review agent prompts receive these variables:

| Variable | Description |
|----------|-------------|
| `$organizational_context` | Organization-specific context from project settings |
| `$document_content` | The document being reviewed |

Chat agent prompts receive these variables:

| Variable | Description |
|----------|-------------|
| `$organizational_context` | Organization-specific context from project settings |
| `$project_name` | Name of the project |
| `$project_description` | Project description |
| `$project_id` | Project identifier |
| `$findings_section` | Prior findings from memory (or "No findings" message) |
| `$chat_history` | Previous conversation messages |
| `$question` | The user's current question |

Structure the prompt with:

1. Domain expertise description (who the agent is)
2. Analysis areas (numbered sections with specific concerns)
3. Severity level definitions (what high/medium/low mean for this domain)
4. Category values (enumerated list)
5. Per-finding instructions (what to include, how to reference)
6. The placeholder sections at the end

Example ending for a review prompt:

```markdown
---

Organizational Context:
$organizational_context

---

Analyze this solution design document:

$document_content
```

See `agents/security_review/prompt.md` for a four-level severity example, or `agents/architecture_review/prompt.md` for a three-level example.

#### requirements.txt

```
bedrock-agentcore
strands-agents[otel]>=1.28.0
pydantic>=2.0.0
boto3>=1.34.0
```

### 2. Create the Chat Agent

Create a matching chat agent for follow-up conversations:

```
agents/
  my_domain_chat/
    agent.py
    prompt.md
    requirements.txt
```

Chat agents follow a simpler pattern — they receive the document content and chat history, and return conversational responses. See `agents/architecture_chat/` for the pattern.

### 3. Register the Agent

#### Agent config (`agent.yaml`)

Each agent directory needs an `agent.yaml` that the deploy script uses to discover and configure the agent:

```yaml
# agents/my_domain_review/agent.yaml
name: my_domain
role: review
ssm_key: agent/my_domain_arn
```

```yaml
# agents/my_domain_chat/agent.yaml
name: my_domain_chat
role: chat
ssm_key: agent/my_domain_chat_arn
```

The deploy script scans `agents/*/agent.yaml` automatically — no script edits needed.

#### Deploy script (`scripts/deploy_agent.sh`)

No changes needed. The script discovers agents from `agent.yaml` files. Run `bash scripts/deploy_agent.sh` with no arguments to see all discovered agents.

#### Seed script (`scripts/seed_agent_registry.sh`)

No changes needed. The seed script automatically discovers all review agents that have a `registry:` block in their `agent.yaml`, reads `prompt.md` and `coach_guidance.md` from the agent directory, and writes everything to DynamoDB.

All registry metadata lives in the review agent's `agent.yaml` — add a `registry:` block with the fields below:

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
  chat_agent: my_domain_chat    # references the chat agent's name from its agent.yaml
  finding_schema:
    severity_levels: [high, medium, low]
    severity_source: direct
    primary_fields: []
    optional_fields: []
    display_strategy: severity_badge
```

The `description` field is critical — it's what the AI planner sees when deciding which agents to include in a review. The planner reasons about jurisdiction, industry, and regulatory context, so:
- Generic agents (architecture, security, risk) should have broad descriptions
- Domain-specific agents should explicitly state their scope: jurisdiction, industry, applicable regulations, and when to select them
- Example: *"Reviews EU regulatory compliance for financial institutions: GDPR, DORA, EBA outsourcing guidelines, PSD2, US CLOUD Act/Schrems II, data sovereignty, NIS2. Select for EU-regulated banks and financial services institutions."*

You can also edit the description later via the admin page without rerunning the seed script.

For agents with derived severity, set `severity_source` to `"derived"` and add the derivation fields:

```yaml
  finding_schema:
    severity_levels: [critical, high, medium, low]
    severity_source: derived
    severity_derivation: "likelihood × consequence matrix (ISO 31000)"
    primary_fields: [likelihood, consequence]
    optional_fields: [residual_risk]
    display_strategy: likelihood_consequence
```

Chat agents don't need a `registry:` block — they're referenced from their review agent's yaml via the `chat_agent` field. The seed script resolves the chat agent's SSM key automatically by finding the matching `agent.yaml`.

#### AgentCore config (`.bedrock_agentcore.yaml`)

Add agent entries for both review and chat agents. Follow the existing pattern in the file.

### 4. Coach Guidance

Coach guidance tells the quality judge what "good" looks like for your domain. Create a `coach_guidance.md` file in your agent's review directory:

```
agents/
  my_domain_review/
    coach_guidance.md   # Quality judge evaluation criteria
```

Define completeness checks, specificity checks, and actionability checks for your domain. See `agents/risk_review/coach_guidance.md` or `agents/eu_regulatory_review/coach_guidance.md` for examples.

The seed script automatically reads `coach_guidance.md` and stores it in the registry. You can also update it later via the admin page (Edit → "Upload .md" button) without rerunning the seed script.

Without coach guidance, the quality judge will auto-disable coaching for this agent during plan creation and show a warning. The review still runs — coaching is just skipped.

### 5. Deploy

```bash
# Deploy the review agent
task deploy:agent -- my_domain

# Deploy the chat agent
task deploy:agent -- my_domain_chat

# Grant memory access to the chat agent
task deploy:iam

# Seed the registry with the new agent metadata
task deploy:seed
```

After seeding, the new agent appears automatically in:
- Review plan creation (planner can select it)
- Plan customize panel (users can add/remove it)
- Project detail tabs (findings display)
- Chat panel (follow-up conversations)
- Analytics dashboard (quality scores)

## Display Strategies

The frontend renders finding cards based on the `display_strategy` in the agent registry. No frontend changes needed for standard strategies:

| Strategy | When to Use | Example Agent |
|----------|-------------|---------------|
| `severity_badge` | Standard severity (high/medium/low) | automotive compliance |
| `severity_badge_with_tags` | Severity + reference tags (OWASP, CWE) | security |
| `likelihood_consequence` | Risk-style likelihood × consequence | risk |
| `quality_attribute` | Quality attributes + impact types | architecture |

Adding a new display strategy requires a frontend code change in `finding-card.jsx`.
