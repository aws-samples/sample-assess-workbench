// Demo event sequence for the live review visualization.
// Exercises: document processing, image analysis, plan creation,
// coach loop (security rejected then accepted, risk accepted first try),
// quality evaluation, and review completion.

export const DEMO_STEPS = [
  { event: 'document_processing_started', delay: 1400, detail: { total_files: 2 } },
  { event: 'file_processing_started', delay: 1600, detail: { filename: 'architecture-spec.pdf', file_type: 'pdf', index: 1, total_files: 2 } },
  { event: 'file_text_extracted', delay: 1200, detail: { filename: 'architecture-spec.pdf', file_type: 'pdf', pages: 12, images: 3, size_kb: 142, index: 1, total_files: 2 } },
  { event: 'file_processing_started', delay: 1400, detail: { filename: 'api-design.md', file_type: 'md', index: 2, total_files: 2 } },
  { event: 'file_text_extracted', delay: 1600, detail: { filename: 'api-design.md', file_type: 'md', pages: 0, images: 0, size_kb: 4.2, index: 2, total_files: 2 } },
  { event: 'all_files_processed', delay: 400, detail: { total_files: 2, total_pages: 12, total_images: 3, combined_size_kb: 146.2 } },
  // Image analysis
  { event: 'image_analysis_started', delay: 600, detail: { total_images: 3, filenames: ['architecture-spec.pdf'] } },
  { event: 'image_classified', delay: 800, detail: { filename: 'architecture-spec.pdf', page_num: 1, image_index: 0, category: 'logo', relevant: false, confidence: 0.95, brief_description: 'Company logo', triage_tokens: { input: 280, output: 45 } } },
  { event: 'image_skipped', delay: 200, detail: { filename: 'architecture-spec.pdf', page_num: 1, image_index: 0, category: 'logo', reason: 'Not architecturally relevant' } },
  { event: 'image_classified', delay: 800, detail: { filename: 'architecture-spec.pdf', page_num: 3, image_index: 0, category: 'architecture_diagram', relevant: true, confidence: 0.98, brief_description: 'AWS architecture diagram showing ECS and Aurora', triage_tokens: { input: 310, output: 52 } } },
  { event: 'image_analyzed', delay: 2000, detail: { filename: 'architecture-spec.pdf', page_num: 3, image_index: 0, diagram_type: 'architecture_diagram', component_count: 8, connection_count: 6, analysis_tokens: { input: 1200, output: 850 } } },
  { event: 'image_classified', delay: 800, detail: { filename: 'architecture-spec.pdf', page_num: 7, image_index: 0, category: 'sequence_diagram', relevant: true, confidence: 0.92, brief_description: 'Authentication flow sequence diagram', triage_tokens: { input: 295, output: 48 } } },
  { event: 'image_analyzed', delay: 2000, detail: { filename: 'architecture-spec.pdf', page_num: 7, image_index: 0, diagram_type: 'sequence_diagram', component_count: 4, connection_count: 8, analysis_tokens: { input: 980, output: 720 } } },
  { event: 'image_analysis_completed', delay: 400, detail: { total_images: 3, analyzed: 2, skipped: 1, total_tokens: 3500, duration_ms: 6200 } },
  // Document loaded, planning begins
  { event: 'document_loaded',  delay: 1800,  detail: { size_kb: 146.2, total_files: 2, total_pages: 12, total_images: 3, images_analyzed: 2, images_skipped: 1, image_analysis_tokens: 3500 } },
  { event: 'registry_loaded',  delay: 1600,  detail: { agent_count: 3, agents: ['architecture', 'security', 'risk'] } },
  { event: 'plan_created',     delay: 9000, detail: {
    plan: {
      document_type: 'microservices_architecture', complexity: 'high',
      rationale: 'Distributed event-driven system with PII handling and multi-region deployment.',
      groups: [
        { group_id: 'initial', label: 'Initial Reviews', execution: 'parallel',
          agents: [
            { agent_type: 'architecture', depth: 'thorough', focus_areas: ['event patterns', 'scaling', 'data flow'], depends_on: [], prompt_addendum: '', coach_guidance: 'loaded', judge: { enabled: true, max_iterations: 3, quality_threshold: 0.8 } },
            { agent_type: 'security', depth: 'thorough', focus_areas: ['auth', 'PII/HIPAA', 'encryption'], depends_on: [], prompt_addendum: '', coach_guidance: 'loaded', judge: { enabled: true, max_iterations: 3, quality_threshold: 0.8 } },
          ]},
        { group_id: 'risk', label: 'Risk Assessment', execution: 'sequential',
          agents: [
            { agent_type: 'risk', depth: 'thorough', focus_areas: ['operational', 'vendor lock-in', 'DR'],
              depends_on: ['architecture', 'security'], prompt_addendum: '', coach_guidance: 'loaded', judge: { enabled: true, max_iterations: 3, quality_threshold: 0.8 } },
          ]},
      ],
    },
    requires_approval: true,
  }},
  // --- Group 1: architecture (coach enabled) + security (coach enabled) ---
  { event: 'agent_started',    delay: 1200,  detail: { agent: 'architecture', iteration: 0, max_iterations: 3 } },
  { event: 'agent_started',    delay: 200,  detail: { agent: 'security', iteration: 0, max_iterations: 3 } },
  { event: 'agent_completed',  delay: 8000, detail: { agent: 'architecture', finding_count: 8, iteration: 0, metrics: { total_tokens: 14200, input_tokens: 11800, output_tokens: 2400, cycle_count: 2, total_duration_s: 5.8, model_latency_ms: 4900, cache_read_tokens: 3200 } } },
  { event: 'agent_tool_calls', delay: 200, detail: { agent: 'architecture', tool_calls: [
    { tool: 'search_document', args: { query: 'event-driven architecture' }, duration_ms: 280, result_count: 4 },
    { tool: 'search_document', args: { query: 'scaling strategy' }, duration_ms: 310, result_count: 3 },
    { tool: 'lookup_standard', args: { standard: 'iso-25010', query: 'quality attributes' }, duration_ms: 150, result_count: 2 },
  ] } },
  { event: 'agent_memory_write', delay: 200, detail: { agent: 'architecture', records: 8, namespace: '/findings/demo-project/architecture' } },
  // Coach accepts architecture on first pass
  { event: 'judge_evaluated',  delay: 3000, detail: { agent: 'architecture', score: 0.87, quality_met: true, iteration: 0, critique_summary: '' } },
  { event: 'agent_completed',  delay: 2000, detail: { agent: 'security', finding_count: 9, iteration: 0, metrics: { total_tokens: 12400, input_tokens: 9800, output_tokens: 2600, cycle_count: 2, total_duration_s: 5.2, model_latency_ms: 4400, cache_read_tokens: 2800 } } },
  { event: 'agent_tool_calls', delay: 200, detail: { agent: 'security', tool_calls: [
    { tool: 'search_document', args: { query: 'authentication mechanism' }, duration_ms: 260, result_count: 3 },
    { tool: 'search_document', args: { query: 'encryption at rest' }, duration_ms: 290, result_count: 2 },
    { tool: 'lookup_standard', args: { standard: 'owasp-top-10', query: 'broken access control' }, duration_ms: 180, result_count: 2 },
    { tool: 'lookup_standard', args: { standard: 'cwe', section: 'CWE-287' }, duration_ms: 140, result_count: 1 },
  ] } },
  { event: 'agent_memory_write', delay: 200, detail: { agent: 'security', records: 9, namespace: '/findings/demo-project/security' } },
  // Coach rejects security — score below threshold
  { event: 'judge_evaluated',  delay: 5000, detail: { agent: 'security', score: 0.62, quality_met: false, iteration: 0, critique_summary: 'Missing OWASP mappings for auth findings. Encryption analysis lacks specificity.' } },
  // Security retries with critique
  { event: 'agent_started',    delay: 3000, detail: { agent: 'security', iteration: 1, max_iterations: 3 } },
  { event: 'agent_completed',  delay: 8000, detail: { agent: 'security', finding_count: 12, iteration: 1, metrics: { total_tokens: 18600, input_tokens: 14100, output_tokens: 4500, cycle_count: 3, total_duration_s: 7.2, model_latency_ms: 6100, cache_read_tokens: 4800 } } },
  { event: 'agent_tool_calls', delay: 200, detail: { agent: 'security', tool_calls: [
    { tool: 'search_document', args: { query: 'PII handling HIPAA' }, duration_ms: 270, result_count: 3 },
    { tool: 'lookup_standard', args: { standard: 'owasp-top-10', query: 'injection' }, duration_ms: 160, result_count: 2 },
    { tool: 'get_prior_findings', args: { agent_type: 'architecture', query: 'authentication' }, duration_ms: 340, result_count: 2 },
  ] } },
  { event: 'agent_memory_write', delay: 200, detail: { agent: 'security', records: 12, namespace: '/findings/demo-project/security' } },
  // Coach accepts security on iteration 2
  { event: 'judge_evaluated',  delay: 4000, detail: { agent: 'security', score: 0.84, quality_met: true, iteration: 1, critique_summary: '' } },
  // --- Group 2: risk (coach enabled, passes first try) ---
  { event: 'agent_started',    delay: 1500,  detail: { agent: 'risk', iteration: 0, max_iterations: 3 } },
  { event: 'agent_completed',  delay: 8000, detail: { agent: 'risk', finding_count: 5, iteration: 0, metrics: { total_tokens: 11400, input_tokens: 9200, output_tokens: 2200, cycle_count: 2, total_duration_s: 4.6, model_latency_ms: 3800, cache_read_tokens: 2100 } } },
  { event: 'agent_tool_calls', delay: 200, detail: { agent: 'risk', tool_calls: [
    { tool: 'get_prior_findings', args: { agent_type: 'architecture', query: 'availability risks' }, duration_ms: 320, result_count: 3 },
    { tool: 'get_prior_findings', args: { agent_type: 'security', query: 'critical vulnerabilities' }, duration_ms: 310, result_count: 4 },
    { tool: 'search_document', args: { query: 'disaster recovery' }, duration_ms: 250, result_count: 2 },
    { tool: 'lookup_standard', args: { standard: 'iso-31000', query: 'risk treatment' }, duration_ms: 170, result_count: 2 },
  ] } },
  { event: 'agent_memory_write', delay: 200, detail: { agent: 'risk', records: 5, namespace: '/findings/demo-project/risk' } },
  // Coach accepts risk on first pass
  { event: 'judge_evaluated',  delay: 3000, detail: { agent: 'risk', score: 0.88, quality_met: true, iteration: 0, critique_summary: '' } },
  // --- Post-execution ---
  { event: 'memory_write',     delay: 1500,  detail: { records: 25 } },
  { event: 'aggregation_complete', delay: 1500, detail: { total_findings: 25, critical_severity: 1, high_severity: 3, medium_severity: 10, low_severity: 11 } },
  { event: 'quality_evaluation_started', delay: 1000, detail: { agent_count: 3 } },
  { event: 'quality_score',    delay: 2500, detail: { agent: 'architecture', overall: 0.85, scores: { completeness: 0.88, specificity: 0.80, actionability: 0.87 }, quality_met: true } },
  { event: 'quality_score',    delay: 2000,  detail: { agent: 'security', overall: 0.78, scores: { completeness: 0.82, specificity: 0.71, actionability: 0.81 }, quality_met: false } },
  { event: 'quality_score',    delay: 1500,  detail: { agent: 'risk', overall: 0.91, scores: { completeness: 0.93, specificity: 0.88, actionability: 0.92 }, quality_met: true } },
  { event: 'quality_evaluation_complete', delay: 800, detail: { scores: { architecture: 0.85, security: 0.78, risk: 0.91 } } },
  { event: 'review_complete',  delay: 1200, detail: { total_findings: 25, critical_severity: 1, high_severity: 3, medium_severity: 10, low_severity: 11, duration_ms: 34200, metrics: { total_tokens: 68500, input_tokens: 53100, output_tokens: 15400, cache_read_tokens: 12900, total_cycles: 10, image_analysis: { total_tokens: 3500, images_analyzed: 2, images_skipped: 1, duration_ms: 6200 }, judge: { total_tokens: 9200, input_tokens: 7100, output_tokens: 2100, by_agent: { architecture: 1.4, security: 2.8, risk: 1.1 } }, by_agent: { architecture: { total_tokens: 14200, cycle_count: 2, total_duration_s: 5.8, lambda_duration_s: 7.2, model_latency_ms: 4900, coach_durations: [1.5] }, security: { total_tokens: 31000, cycle_count: 5, total_duration_s: 12.4, lambda_duration_s: 15.8, model_latency_ms: 10500, coach_durations: [1.6, 1.4] }, risk: { total_tokens: 11400, cycle_count: 2, total_duration_s: 4.6, lambda_duration_s: 5.9, model_latency_ms: 3800, coach_durations: [1.2] } } } } },
];
