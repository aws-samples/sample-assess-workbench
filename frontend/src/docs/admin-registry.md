# Registered Agents

> Admin access required

## What Is the Registry?

The agent registry is the central configuration for all review agents. It controls how agents appear in the UI, their quality coaching settings, and their finding display strategies. Changes take effect immediately — no redeployment needed.

## Editing an Agent

From the **Admin** page:

1. Click **Edit** on any agent row
2. Modify the available settings:
   - **Enabled/Disabled** — toggle whether the agent appears in review plans
   - **Coach** — enable/disable quality coaching for this agent
   - **Threshold** — quality score threshold for coaching (0.5–1.0). Higher = stricter
   - **Sort Order** — controls the display order in tabs and plans
3. Click **Save**

## What You Can't Change Here

The admin page manages metadata, not infrastructure:

- **Agent code and prompts** — edit in the codebase and redeploy via AgentCore
- **Agent ARNs** — managed by deploy scripts and SSM parameters
- **Model selection** — the review model is set at deploy time; use benchmarks to compare models
- **Finding schemas** — display strategies are set in the seed script

## Display Strategies

Each agent has a display strategy that controls how findings render:

| Strategy | Description | Used By |
|----------|-------------|---------|
| `severity_badge` | Standard severity badge | Default, Auto Compliance |
| `severity_badge_with_tags` | Severity + OWASP/CWE/compliance tags | Security |
| `likelihood_consequence` | Likelihood × Consequence with derived severity | Risk |
| `quality_attribute` | Severity + quality attribute + impact type | Architecture |
