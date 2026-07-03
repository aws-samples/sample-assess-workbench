# Reading Findings

## Severity Levels

Findings use a severity scale that varies by agent:

| Level | Color | Meaning |
|-------|-------|---------|
| Critical | Purple | Immediate action required — system compromise, data breach, or catastrophic risk |
| High | Red | Serious issue requiring prompt attention |
| Medium | Yellow | Notable concern that should be addressed |
| Low | Green | Minor improvement opportunity or best practice deviation |

Architecture findings use three levels (high/medium/low). Security, risk, and AU FSI compliance findings use four levels (critical/high/medium/low).

## Agent-Specific Fields

### Architecture Findings
- **Quality Attribute** — ATAM attribute: performance, modifiability, availability, security, usability, testability, interoperability, deployability
- **Impact Type** — risk, sensitivity point, tradeoff, or recommendation
- **Affected Components** — specific system components involved

### Security Findings
- **OWASP Category** — mapping to OWASP Top 10 2021 (e.g., "A01:2021 Broken Access Control")
- **CWE ID** — Common Weakness Enumeration identifier (e.g., "CWE-287")
- **Compliance Refs** — relevant regulations (e.g., "GDPR Art.32", "SOC2 CC6.1")

### Risk Findings
- **Likelihood** — almost certain, likely, possible, unlikely, rare
- **Consequence** — catastrophic, major, moderate, minor, insignificant
- **Risk Treatment** — mitigate, transfer, accept, avoid
- **Severity** — derived from the likelihood × consequence matrix

### AU FSI Compliance Findings
- **Regulatory Reference** — the specific provision the finding maps to (e.g., "CPS 234 paragraph 14", "APP 11.1", "ASIC RG 271")
- **Obligation Type** — mandatory (prudential standard or legislation), guidance (CPG or regulatory guidance), or best practice (industry framework)
- **Compliance Gap** — non-compliant, partially compliant, or insufficient evidence
- **Remediation Timeframe** — immediate, short-term, medium-term, or long-term (optional)
- **Authority Level** — prudential standard, regulatory guidance, regulatory commentary, industry framework, or legislation (optional)

## Providing Feedback

Each finding has thumbs up/down buttons. Your feedback:
- Helps track which findings are genuinely useful
- Feeds into the analytics dashboard's agreement rates
- Guides future prompt tuning — findings with high downvote rates are candidates for improvement

Feedback is per-user — different team members can rate the same finding independently.
