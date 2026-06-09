# Organizational Contexts

## What Are Contexts?

Context documents describe your organization's business environment, regulatory requirements, and technology standards. When applied to a project, agents tailor their findings to your specific situation.

For example, a fintech context mentioning PCI DSS compliance will cause the security agent to focus on payment data handling, and the risk agent to flag compliance gaps specific to financial services.

## Creating a Context

1. Go to the **Contexts** page from the nav bar
2. Click **+ New Context**
3. Enter a name (e.g., "ACME Corp — Financial Services") and description
4. Upload a markdown or text file describing your organization's environment
5. Click **Create & Upload**

## What to Include

A good context document covers:

- **Industry** — what sector you operate in, key regulations
- **Technology stack** — cloud provider, key services, deployment model
- **Compliance requirements** — GDPR, SOC2, PCI DSS, HIPAA, etc.
- **Security posture** — existing controls, threat model, risk appetite
- **Architecture standards** — preferred patterns, technology choices, constraints

## Example Context Document

Here's an example of what a well-structured context document looks like:

```markdown
# ACME Financial Services — Organizational Context

## Industry & Regulation
- Retail banking and wealth management (Australia)
- Regulated by APRA and ASIC
- Key standards: CPS 234 (Information Security), CPS 230 (Operational Risk),
  PCI DSS 4.0, ISO 27001:2022

## Technology Stack
- Multi-account AWS deployment (Landing Zone)
- Container workloads on EKS, serverless APIs on Lambda
- Data lake on S3 with Glue ETL, Redshift for analytics
- CI/CD via CodePipeline with manual approval gates for production

## Compliance Requirements
- All customer data classified as HIGHLY PROTECTED
- Data residency: ap-southeast-2 only (no cross-region replication)
- Annual penetration testing, quarterly vulnerability scanning
- SOC 2 Type II attestation maintained

## Risk Appetite
- Zero tolerance for unencrypted PII at rest or in transit
- Maximum RTO: 4 hours for critical systems, 24 hours for non-critical
- Third-party services must meet APRA CPS 234 outsourcing requirements
```

Keep contexts concise and factual — agents use them as background context, not as the primary assessment target.

## Applying to Projects

When creating a new project, select a context from the dropdown. The context is passed to all review agents alongside the design document. You can review and edit context content from the Contexts page at any time.
