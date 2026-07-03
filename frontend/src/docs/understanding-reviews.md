# Understanding Reviews

## Review Agents

The system uses specialized AI agents, each focused on a different dimension of your design:

- **🏗️ Architecture** — Evaluates design patterns, scalability, performance, maintainability. Uses ATAM (Architecture Tradeoff Analysis Method) quality attributes. Findings include impact types: risk, sensitivity point, tradeoff, or recommendation.
- **🔒 Security** — Analyzes authentication, authorization, data protection, network security, and compliance. Maps findings to OWASP Top 10 and CWE identifiers where applicable.
- **⚠️ Risk** — Assesses technical, operational, and business risks using ISO 31000 framework. Uses a 5×5 likelihood × consequence matrix to derive severity.
- **🏛️ AU FSI Compliance** — Assesses design compliance against Australian financial services regulation: APRA prudential standards (CPS 230, CPS 234) and practice guides (CPG 230, CPG 234), ASIC obligations, the Privacy Act (Australian Privacy Principles), and AUSTRAC AML/CTF requirements. Maps each finding to a specific regulatory reference. Select for entities regulated by APRA, ASIC, or AUSTRAC.

This is the shipped set. Because agents are fully customizable, your deployment may include different domain specialists — the registry is the source of truth.

## Plan Approval

Before agents execute, the AI planner creates a review strategy. You can:

- **Approve as-is** — accept the AI's plan
- **Customize** — adjust per-agent settings:
  - Depth (quick / standard / thorough)
  - Focus areas (e.g., "auth", "PII", "encryption")
  - Add or remove agents
  - Reorder execution groups (parallel vs sequential)
  - Enable/disable quality coaching per agent
  - Add prompt addendums for extra instructions

## Quality Coaching

When enabled for an agent, a quality judge evaluates the agent's findings after each iteration:

1. Agent produces findings
2. Judge scores them on completeness, specificity, and actionability
3. If the score meets the threshold → accepted
4. If not → judge provides critique, agent retries with feedback
5. Repeats up to the configured max iterations

This improves finding quality but adds time and cost. You can see iteration counts on the live review page.

## Quality Scores

Every review includes quality scores per agent:

- **Completeness** (0–1) — Are all relevant aspects of the focus areas covered?
- **Specificity** (0–1) — Do findings reference specific parts of the document?
- **Actionability** (0–1) — Can a team act on each finding without further clarification?
- **Overall** — Average of the three criteria

Scores appear as badges on the findings panel and in the analytics dashboard.
