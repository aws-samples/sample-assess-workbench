Evaluate this Australian financial services compliance review against APRA
prudential standards (CPS 230, CPS 234), their practice guides (CPG 230,
CPG 234), ASIC obligations, the Privacy Act 1988 / Australian Privacy
Principles, and AUSTRAC AML/CTF obligations. Judge the quality of the compliance
analysis — not whether the design is technically secure or operationally risky
(other agents own those).

Required fields per finding:
- regulatory_reference: Must cite a specific, verifiable provision — a paragraph,
  section, article, or principle (e.g. a CPS paragraph number, an APP number, an
  ASIC regulatory guide). A bare standard name with no provision is insufficient.
- obligation_type: Must be one of mandatory / guidance / best_practice, and must
  match the source — prudential standards and legislation are mandatory, practice
  guides and regulatory guidance are guidance, industry frameworks are
  best_practice.
- compliance_gap: Must be one of non_compliant / partially_compliant /
  insufficient_evidence, and the choice must be justified. "insufficient_evidence"
  means the design is silent on the requirement, not that it breaches it.
- remediation_timeframe: Should be set where a gap needs remediation, and be
  proportionate to severity (a critical mandatory breach should not be long_term).
- authority_level: Should distinguish the source's regulatory weight (prudential
  standard vs regulatory guidance vs legislation, etc.).

Citation accuracy checks (the highest-value dimension for this agent):
- Does every citation point to a specific provision the reviewer verified via
  lookup_standard, rather than a number recalled from memory? Reward findings
  that cite looked-up text; flag citations asserted without verification.
- Is the mandatory-vs-guidance distinction framed correctly in the language —
  "required by / must" for CPS and legislation, "APRA expects / better practice"
  for CPG and guidance?
- Where a finding spans a mandatory requirement and its practice-guide guidance,
  are both cited with their authority levels distinguished?
- Are notification and timing obligations assessed against the *trigger the
  standard actually specifies* (e.g. awareness of an incident vs the incident
  date), with the exact trigger and timeframe verified via lookup_standard rather
  than assumed? A design that anchors a notification clock to the wrong trigger
  is a compliance defect worth flagging.

Completeness checks:
- Are the applicable review areas covered given the document and organisational
  context? (CPS 230 operational resilience, CPS 234 information security, CPG
  230/234 practice-guide expectations, ASIC obligations, Privacy Act / APPs,
  AUSTRAC AML/CTF where applicable.)
- Are cross-agent connections made rather than duplicated — security findings
  mapped to CPS 234 obligations, risk findings to CPS 230 obligations,
  architecture findings to business-continuity/disaster-recovery compliance —
  each adding the regulatory-compliance lens rather than restating the technical
  finding?
- For third-party, cloud, or service-provider dependencies, is the compliance
  obligation on the regulated entity assessed (not just the technical risk)?

Specificity checks:
- Do findings reference specific document sections, controls, or clauses rather
  than generic compliance observations?
- Is each finding a genuine regulatory-compliance gap, not a security or risk
  finding repeated without the compliance perspective added?
- Are APRA supervisory-commentary points framed as regulatory signals
  ("APRA's recent supervisory activity indicates…") rather than binding
  requirements?

Actionability checks:
- Do recommendations specify concrete compliance steps (e.g. the specific
  control, notification process, or contractual clause to add) rather than
  "improve compliance"?
- Is severity calibrated correctly — critical/high reserved for breaches of
  mandatory prudential-standard or legislative requirements likely to draw
  supervisory action, not gaps against practice-guide guidance or best practice?
- Are remediation timeframes realistic and proportionate to the severity and
  nature of the gap?
