# Architecture Overview

High-level view of how the Solution Design Review application fits together. This is the "explain the system in one picture" diagram — logical components, not AWS services or Lambda function names. For concrete AWS resources, see [aws-services.md](aws-services.md). For the narrative walkthrough, see [system-overview.md](system-overview.md).

> **Last verified:** 2026-04-21 against `terraform/`, `api/`, and `agents/`. Re-verify when adding a new subsystem (auth model, new agent class, new KB).

## The big picture

```mermaid
graph TB
    User([User])

    subgraph Frontend["Frontend (SPA)"]
        SPA[Preact + Vite<br/>served from S3/CloudFront or<br/>local Vite dev server]
    end

    subgraph Auth["Identity"]
        IdP[Cognito User Pool<br/>Hosted UI + JWT]
    end

    subgraph Edge["Edge (staging/prod)"]
        CF[CloudFront + WAF<br/>unified ingress —<br/>SPA, API, WebSocket]
    end

    subgraph API["Application API"]
        REST[REST API<br/>Projects, Contexts,<br/>Reviews, Agent Registry]
        WS[WebSocket API<br/>Chat + live review events]
    end

    subgraph Workflow["Adaptive Review Workflow"]
        Planner[AI Planner<br/>produces review plan]
        Approval{{User approval<br/>pause point}}
        Executor[Group Executor<br/>sequential groups,<br/>parallel agents]
        Aggregator[Aggregator + Judge<br/>scores findings]
    end

    subgraph Agents["Review & Chat Agents"]
        ReviewAgents[Review Agents<br/>architecture, security, risk,<br/>compliance — produce findings]
        ChatAgents[Chat Agents<br/>one per domain —<br/>conversational Q&A]
    end

    subgraph Knowledge["Knowledge & Memory"]
        Memory[(Semantic Memory<br/>review findings,<br/>scoped by project + domain)]
        DocKB[(Document KB<br/>uploaded project docs,<br/>RAG for agents)]
        StdKB[(Standards KB<br/>compliance standards<br/>& policies)]
    end

    subgraph Storage["Storage"]
        Docs[(Document & Context<br/>file storage)]
        AppData[(Application data<br/>projects, reviews,<br/>plans, chat history,<br/>agent registry)]
    end

    User -->|login| IdP
    User -->|requests with JWT| SPA
    SPA -->|all traffic| CF
    CF -->|/| SPA
    CF -->|/api/*| REST
    CF -->|/ws| WS

    REST -->|read/write| AppData
    REST -->|pre-signed URLs<br/>upload/download| Docs
    REST -->|trigger / approve plan| Workflow

    Workflow --> Planner
    Planner --> Approval
    Approval -->|user approves| Executor
    Executor -->|invoke| ReviewAgents
    Executor --> Aggregator
    Aggregator -->|write findings| Memory
    Aggregator -->|write results| AppData

    Workflow -.live progress.-> WS
    WS -.events via CF.-> SPA

    WS -->|chat messages| ChatAgents
    ChatAgents -->|retrieve findings| Memory
    ChatAgents -->|retrieve context| DocKB
    ChatAgents -->|lookup standards| StdKB
    ReviewAgents -->|retrieve context| DocKB
    ReviewAgents -->|lookup standards| StdKB

    classDef user fill:#e1f5ff,stroke:#333,color:#000
    classDef frontend fill:#fff2cc,stroke:#333,color:#000
    classDef auth fill:#f8cecc,stroke:#333,color:#000
    classDef edge fill:#ffe6cc,stroke:#333,color:#000
    classDef api fill:#dae8fc,stroke:#333,color:#000
    classDef workflow fill:#e1d5e7,stroke:#333,color:#000
    classDef agents fill:#d5e8d4,stroke:#333,color:#000
    classDef knowledge fill:#ffe6cc,stroke:#333,color:#000
    classDef storage fill:#fff2cc,stroke:#333,color:#000

    class User user
    class SPA frontend
    class IdP auth
    class CF edge
    class REST,WS api
    class Planner,Approval,Executor,Aggregator workflow
    class ReviewAgents,ChatAgents agents
    class Memory,DocKB,StdKB knowledge
    class Docs,AppData storage
```

## How it flows

The application has three interaction modes, all gated by Cognito. In staging/prod, all browser traffic enters through a single CloudFront distribution with WAF — the SPA, API calls, and WebSocket connections share one edge. In dev, the Vite dev server talks to API Gateway directly.

**Authoring a project.** The user uploads one or more design documents through the SPA. The REST API issues pre-signed URLs so the browser uploads directly to object storage, and writes project metadata to the application data store.

**Running a review.** The user triggers a review through the REST API. The Adaptive Review Workflow takes over:

1. An AI planner reads the document(s) and produces a tailored review plan — which agents to run, how to group them (parallel within a group, sequential across groups), which focus areas to emphasise, and how deeply to dig.
2. The workflow pauses for user approval of the plan. The SPA displays it; the user can modify it.
3. Once approved, the executor invokes review agents group by group. Agents read the document, pull context from the Document KB and Standards KB, and produce structured findings.
4. The aggregator collects findings, a judge scores them, and results are written to both the application data store and semantic memory.

Throughout the workflow, progress events flow out through the WebSocket API so the SPA can render live progress.

**Chatting about findings.** Once a review is complete, the user opens a chat tab for any domain (architecture, security, risk, compliance). Chat agents retrieve relevant findings from semantic memory, supplement them with the original document and standards lookups, and stream responses back through the WebSocket.

## What's deliberately not shown

- **AWS service names.** API Gateway, Lambda, Step Functions, DynamoDB, S3, Bedrock — those live in [aws-services.md](aws-services.md). The components here map cleanly to AWS services but naming them up front obscures the logical structure.
- **Individual Lambda functions.** Each box above may be one or several Lambdas. The boundary that matters for understanding the system is the logical subsystem, not the execution unit.
- **Security boundaries and encryption.** Auth is shown as a gate here but the full picture — trust boundaries, IAM roles, encryption at rest and in transit, origin lockdown — is in [security-architecture.md](security-architecture.md).

## Key design choices

- **Adaptive, not fixed.** The review plan is generated per-document by an AI planner, not hardcoded. Adding a new review agent means updating the agent registry, not changing orchestration code.
- **Findings as first-class data.** Review agents produce structured findings (not free-text summaries). The same findings drive the UI, the chat context, and any downstream analysis.
- **Memory is separate from conversation.** Semantic memory is populated by the review workflow and read by chat agents. Chat history lives in the application data store. This keeps review findings searchable across projects without mixing conversational turns into the index.
- **WebSocket for everything real-time.** Both chat and live review progress flow through the WebSocket API. The REST API is strictly request/response.
