# Architecture Overview

Assess Workbench is a serverless application built on AWS, designed for scalable, automated design review using specialized AI agents.

<img src="/docs/arch-light.png" alt="Architecture diagram" class="only-light">
<img src="/docs/arch-dark.png" alt="Architecture diagram" class="only-dark">

## High-Level Flow

1. **Frontend** — A Preact single-page application served from S3 via CloudFront. Handles project creation, document upload, review visualization, and agent chat.
2. **API Layer** — API Gateway (REST) backed by Lambda functions. Handles authentication via Cognito, request validation, and routing.
3. **Orchestration** — AWS Step Functions coordinates the review workflow: document processing → planning → agent execution → quality evaluation → completion.
4. **AI Agents** — Specialized review agents run on Amazon Bedrock AgentCore. Each agent has its own prompt, tools, and domain expertise.
5. **Storage** — S3 for documents and artifacts, DynamoDB for projects, reviews, findings, and agent configuration.

## Key Components

### Document Processing

When a project is created, uploaded documents are processed into a format suitable for agent review:

- **Text extraction** from PDFs and other document formats
- **Image analysis** for diagrams and screenshots
- **Content chunking** for large documents

### AI Planner

The planner analyzes the document and creates a review strategy:

- Selects which agents to include based on document content
- Determines execution order (parallel groups, sequential chains)
- Sets depth and focus areas per agent
- Users can customize the plan before approving

### Agent Execution

Each agent runs independently with:

- A domain-specific system prompt
- Access to the document content and organizational context
- Tools for structured finding output
- Optional quality coaching loop with a judge agent

### Quality Coaching

An optional feedback loop where a judge agent evaluates findings:

- Scores completeness, specificity, and actionability
- Provides critique for improvement
- Agent retries with feedback until threshold is met or max iterations reached

### Real-Time Updates

WebSocket connections provide live updates during review execution:

- Agent progress and status changes
- Finding counts as they arrive
- Quality scores and coach iterations

## Infrastructure

| Component | AWS Service |
|-----------|-------------|
| Frontend hosting | S3 + CloudFront |
| Authentication | Cognito User Pools |
| API | API Gateway + Lambda |
| Orchestration | Step Functions |
| AI Agents | Bedrock AgentCore |
| LLM Access | Amazon Bedrock |
| Document Storage | S3 |
| Data Storage | DynamoDB |
| Real-Time | API Gateway WebSocket |
| Monitoring | CloudWatch |

## Security

- All API endpoints require Cognito JWT authentication
- Admin operations require membership in the `admins` Cognito group
- Documents are stored in private S3 buckets with server-side encryption
- Bedrock Guardrails filter agent inputs and outputs for safety
- CloudFront edge protection with WAF rules
