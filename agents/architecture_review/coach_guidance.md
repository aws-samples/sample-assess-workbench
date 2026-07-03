Evaluate this architecture review against ATAM (Architecture Tradeoff Analysis Method) standards.

Required fields per finding:
- quality_attribute: Must be from the ATAM set (performance, modifiability, availability, security, usability, testability, interoperability, deployability)
- impact_type: Must be one of: risk, sensitivity_point, tradeoff, recommendation
- affected_components: Should name specific system components from the document, not generic terms

Completeness checks:
- Are all five review areas covered? (design patterns, scalability, performance, maintainability, technical debt)
- Are tradeoffs identified where architectural decisions benefit one quality attribute at the expense of another?
- Are sensitivity points called out where a small change would significantly affect a quality attribute?

Specificity checks:
- Do findings reference specific components, services, or layers from the document?
- Are performance concerns backed by concrete scenarios (e.g., "under 1000 concurrent users" not just "at scale")?
- Do recommendations name specific patterns or technologies, not just "consider improving"?

Actionability checks:
- Can an engineering team implement each recommendation without further research?
- Are recommendations prioritized relative to effort and impact?
- Do findings distinguish between "must fix before production" and "consider for future iterations"?
