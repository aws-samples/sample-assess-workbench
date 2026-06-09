Evaluate this risk review against ISO 31000 risk management standards.

Required fields per finding:
- likelihood: Must be from the standard scale (almost_certain, likely, possible, unlikely, rare)
- consequence: Must be from the standard scale (catastrophic, major, moderate, minor, insignificant)
- risk_treatment: Must be one of: mitigate, transfer, accept, avoid — and the choice should be justified by the risk level
- residual_risk: Should be noted when treatment is recommended

Completeness checks:
- Are all five risk areas covered? (technical risks, operational risks, dependencies & integrations, disaster recovery & business continuity, business impact)
- Are single points of failure identified?
- Are third-party dependency risks assessed (not just listed)?
- Is disaster recovery addressed with specific RTO/RPO considerations?
- Are operational risks covered (deployment complexity, monitoring gaps, incident response)?

Specificity checks:
- Are likelihood and consequence assessments justified with reasoning, not just assigned?
- Do risk descriptions reference specific architectural decisions or components from the document?
- Are dependency risks tied to specific services or vendors mentioned in the design?

Actionability checks:
- Do mitigation recommendations include specific controls or design changes?
- Are risk treatments proportionate to the risk level (don't recommend expensive mitigations for low risks)?
- Is the difference between "accept" and "ignore" clear — accepted risks should have monitoring recommendations?
- Are residual risk levels realistic after proposed treatment?
