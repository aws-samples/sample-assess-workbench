# Acme Corporation Information Security Policy (ACME-ISP)

**Source type:** Organisational policy (internal, binding on all staff and contractors)
**Owner:** Acme Corporation — Office of the Chief Information Security Officer
**Version:** 2.1
**Effective:** 1 January 2026
**Status:** FICTIONAL SAMPLE — this document is a fabricated example shipped with
the Assess Workbench sample so a fresh install has a non-empty Standards Corpus.
It does not describe any real organisation and carries no licensing restrictions.

---

## 1. Purpose and Scope

This policy (ACME-ISP) establishes the minimum information security requirements
for Acme Corporation. It applies to all employees, contractors, and third parties
who access Acme systems, data, or networks, and to all environments — production,
non-production, and developer workstations.

The policy is **principles-based and technology-neutral**: it states the control
objective and the minimum requirement, leaving implementation detail to supporting
standards and runbooks. Where a control says **"must"**, it is mandatory; **"should"**
indicates a strong recommendation that requires documented risk acceptance to waive.

Clauses are numbered (e.g. ACME-ISP-4.2) so that assessments and findings can cite
the specific requirement they relate to.

## 2. Governance and Accountability

### ACME-ISP-2.1 — Ownership

The Chief Information Security Officer (CISO) owns this policy. Each information
system must have a named system owner accountable for its compliance with ACME-ISP.

### ACME-ISP-2.2 — Risk acceptance

Any deviation from a mandatory control must be recorded as a formal risk acceptance,
approved by the system owner and the CISO, with an expiry date no longer than 12
months. Expired risk acceptances are treated as control failures.

### ACME-ISP-2.3 — Review cadence

This policy must be reviewed at least annually, and after any material change to the
threat landscape, regulatory obligations, or business operations.

## 3. Access Control

### ACME-ISP-3.1 — Least privilege

Access to systems and data must be granted on a least-privilege basis. Default-deny
is the required posture: access is granted only where there is a documented business
need.

### ACME-ISP-3.2 — Authentication

All access to Acme systems must require multi-factor authentication (MFA). Shared or
generic accounts are prohibited for interactive access. Service accounts must use
non-interactive credentials scoped to a single workload.

### ACME-ISP-3.3 — Joiners, movers, leavers

Access must be provisioned on role change and revoked within 24 hours of a person
leaving the organisation or changing role. Access rights must be recertified at least
every 6 months for privileged accounts and annually for standard accounts.

### ACME-ISP-3.4 — Privileged access

Administrative access must be time-bound and just-in-time where technically feasible.
Standing administrative privileges require documented justification and quarterly
review.

## 4. Data Protection

### ACME-ISP-4.1 — Classification

All data must be classified as Public, Internal, Confidential, or Restricted.
Handling requirements escalate with classification; Restricted data carries the
strictest controls.

### ACME-ISP-4.2 — Encryption

Confidential and Restricted data must be encrypted in transit using TLS 1.2 or
higher, and at rest using AES-256 or an equivalent approved algorithm. Encryption
keys must be managed in an approved key management service and rotated at least
annually.

### ACME-ISP-4.3 — Data minimisation and retention

Personal and Restricted data must be collected only where necessary and retained no
longer than the documented retention schedule requires. Data past its retention
period must be securely destroyed.

### ACME-ISP-4.4 — Data residency

Restricted data must remain within approved geographic regions. Cross-border transfer
requires CISO approval and a documented legal basis.

## 5. Logging and Monitoring

### ACME-ISP-5.1 — Audit logging

Security-relevant events — authentication, authorisation changes, privileged actions,
and access to Restricted data — must be logged. Logs must capture who, what, when, and
from where.

### ACME-ISP-5.2 — Log integrity and retention

Audit logs must be tamper-evident, stored separately from the systems that generate
them, and retained for at least 12 months. Log access must itself be logged.

### ACME-ISP-5.3 — Detection

Security monitoring must alert on anomalous authentication, privilege escalation, and
exfiltration patterns. Alerts must route to a monitored channel with a defined
response owner.

## 6. Change and Configuration Management

### ACME-ISP-6.1 — Change control

Changes to production systems must follow a documented change process with peer review
and the ability to roll back. Emergency changes must be retrospectively reviewed within
5 business days.

### ACME-ISP-6.2 — Secure configuration

Systems must be deployed from approved, hardened baselines. Configuration drift from
the baseline must be detected and remediated.

### ACME-ISP-6.3 — Vulnerability management

Known vulnerabilities must be remediated within risk-based timeframes: Critical within
7 days, High within 30 days, Medium within 90 days. Internet-facing Critical
vulnerabilities must be prioritised.

## 7. Resilience and Incident Response

### ACME-ISP-7.1 — Backups

Restricted and business-critical data must be backed up, and restoration must be
tested at least annually. Backups must be protected from the same failure or
compromise as the primary system (e.g. immutable or isolated copies).

### ACME-ISP-7.2 — Incident response

A documented incident response plan must exist, assign roles, and be exercised at least
annually. Suspected security incidents must be reported to the security team without
delay.

### ACME-ISP-7.3 — Business continuity

Business-critical services must have defined recovery time and recovery point
objectives (RTO/RPO), validated through periodic continuity testing.

## 8. Third-Party and Supply Chain Risk

### ACME-ISP-8.1 — Due diligence

Third parties handling Acme Confidential or Restricted data must be assessed for
security before engagement and periodically thereafter, proportionate to the risk they
carry.

### ACME-ISP-8.2 — Contractual controls

Contracts with such third parties must require security obligations equivalent to this
policy, breach notification, and a right to audit or obtain independent assurance.

### ACME-ISP-8.3 — Software supply chain

Software dependencies must be obtained from trusted sources, inventoried, and screened
for known vulnerabilities before use in production.

## 9. Secure Development

### ACME-ISP-9.1 — Security in the lifecycle

Security requirements must be considered at design time. Material changes must undergo
a proportionate threat-modelling and security review before release.

### ACME-ISP-9.2 — Secrets management

Credentials, keys, and tokens must never be committed to source control or embedded in
application code. Secrets must be stored in an approved secrets manager and rotated on
a defined schedule.

### ACME-ISP-9.3 — Separation of environments

Production data must not be used in non-production environments unless it is
de-identified or equivalent controls are applied. Production and non-production
environments must be logically separated.
