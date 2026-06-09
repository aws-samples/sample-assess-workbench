// Event timeline formatting helpers for the live review page.
// Pure functions — no component state, no side effects.

import { fmtTokens } from './format-utils.js';

export function formatEventName(event) {
  return event.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function formatDetail(event, detail, agentsMap) {
  const ag = agentsMap;
  if (event === 'agent_started') return ag[detail.agent]?.label || detail.agent;
  if (event === 'agent_completed') {
    const base = `${ag[detail.agent]?.label || detail.agent} — ${detail.finding_count} findings`;
    if (detail.metrics?.total_tokens) return `${base} · ${fmtTokens(detail.metrics.total_tokens)} tokens · ${detail.metrics.cycle_count || '?'} cycles`;
    return base;
  }
  if (event === 'agent_error') {
    const label = ag[detail.agent]?.label || detail.agent;
    const reason = detail.status_reason || detail.error || 'failed';
    return `${label} — ${reason}`;
  }
  if (event === 'agent_recovered') {
    const label = ag[detail.agent]?.label || detail.agent;
    return `${label} — ${detail.finding_count} findings (recovered: ${detail.status_reason || 'prior iteration'})`;
  }
  if (event === 'agent_failed') {
    const label = ag[detail.agent]?.label || detail.agent;
    return `${label} — failed: ${detail.status_reason || 'unknown error'}`;
  }
  if (event === 'document_loaded') return `${detail.size_kb} KB${detail.total_files > 1 ? ` (${detail.total_files} files)` : ''}`;
  if (event === 'document_processing_started') return `${detail.total_files} file${detail.total_files !== 1 ? 's' : ''}`;
  if (event === 'file_processing_started') return detail.filename;
  if (event === 'file_text_extracted') return `${detail.filename}${detail.pages > 0 ? ` — ${detail.pages} pages` : ` — ${detail.size_kb} KB`}`;
  if (event === 'all_files_processed') return `${detail.total_files} files, ${detail.combined_size_kb} KB${detail.total_pages > 0 ? `, ${detail.total_pages} pages` : ''}`;
  if (event === 'image_analysis_started') return `${detail.total_images} image${detail.total_images !== 1 ? 's' : ''}`;
  if (event === 'image_classified') return `p${detail.page_num}: ${detail.brief_description || detail.category} — ${detail.relevant ? 'relevant' : 'skipped'}`;
  if (event === 'image_analyzed') return `${detail.diagram_type?.replace(/_/g, ' ') || 'diagram'}: ${detail.component_count} components · ${fmtTokens((detail.analysis_tokens?.input || 0) + (detail.analysis_tokens?.output || 0))} tok`;
  if (event === 'image_skipped') return `p${detail.page_num}: ${detail.category} — ${detail.reason || 'skipped'}`;
  if (event === 'image_analysis_completed') return `${detail.analyzed} analyzed, ${detail.skipped} skipped · ${fmtTokens(detail.total_tokens)} tokens`;
  if (event === 'image_triage_started') return `image ${detail.index}/${detail.total}`;
  if (event === 'image_analysis_in_progress') return `${detail.category?.replace(/_/g, ' ')} (p${detail.page_num})`;
  if (event === 'memory_write') return `${detail.records} records`;
  if (event === 'aggregation_complete') return `${detail.total_findings} findings aggregated`;
  if (event === 'quality_evaluation_started') return `${detail.agent_count} agents`;
  if (event === 'quality_score') return `${detail.agent} — ${(detail.overall || 0).toFixed(2)}${detail.quality_met ? ' ✓' : ''}`;
  if (event === 'quality_evaluation_complete') {
    const scores = detail.scores || {};
    return Object.entries(scores).map(([a, s]) => `${a}: ${s.toFixed(2)}`).join(', ');
  }
  if (event === 'quality_evaluation_failed') return detail.error || 'unknown error';
  if (event === 'judge_started') {
    const label = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
    return detail.mode === 'coach'
      ? `${label} — coach iteration ${(detail.iteration || 0) + 1}`
      : `${label} — evaluating quality`;
  }
  if (event === 'judge_evaluated') {
    const label = ag[detail.agent]?.label || detail.agent;
    return detail.quality_met
      ? `${label} — ${(detail.score || 0).toFixed(2)} ✓ (iter ${(detail.iteration || 0) + 1})`
      : `${label} — ${(detail.score || 0).toFixed(2)} ✗ retry (iter ${(detail.iteration || 0) + 1})`;
  }
  if (event === 'workflow_failed') return detail.error || 'unknown error';
  if (event === 'workflow_completed_with_warnings') return detail.warning || 'Post-completion step failed';
  if (event === 'review_aborted') {
    const agents = detail.failed_agents?.join(', ') || 'unknown';
    return `${detail.message || `Aborted — ${agents} failed`}`;
  }
  if (event === 'review_complete') {
    const base = detail.duration_ms
      ? `${detail.total_findings} findings in ${(detail.duration_ms/1000).toFixed(1)}s`
      : `${detail.total_findings} findings`;
    if (detail.metrics?.total_tokens) return `${base} · ${fmtTokens(detail.metrics.total_tokens)} total tokens`;
    return base;
  }
  if (event === 'plan_created') {
    const agents = detail.plan?.groups?.reduce((s,g) => s+g.agents.length, 0) || detail.agent_count || '?';
    const groups = detail.plan?.groups?.length || detail.group_count || '?';
    const duration = detail.planning_duration_ms ? ` in ${(detail.planning_duration_ms / 1000).toFixed(1)}s` : '';
    return `${agents} agents, ${groups} groups${duration}`;
  }
  if (event === 'planning_started') return `AI planner thinking (${detail.model_id?.split('.').pop() || 'model'})…`;
  if (event === 'planning_complete') {
    const duration = detail.planning_duration_ms ? ` in ${(detail.planning_duration_ms / 1000).toFixed(1)}s` : '';
    return `${detail.agent_count || '?'} agents, ${detail.group_count || '?'} groups${duration}`;
  }
  if (event === 'plan_approved') return detail.auto ? 'auto-approved' : 'approved by user';
  return '';
}

export function eventColor(event, detail, agentsMap) {
  // Failures always red
  if (event.includes('failed') || event.includes('error') || event === 'review_aborted') return '#e74c3c';

  // Post-completion warning — amber
  if (event === 'workflow_completed_with_warnings') return '#f39c12';

  // Success
  if (event === 'review_complete') return '#28a745';

  // Agent-scoped events — use the agent's registry color
  const agentKey = detail?.agent;
  if (agentKey && agentsMap?.[agentKey]?.color) {
    return agentsMap[agentKey].color;
  }

  // Plan/orchestrator events
  if (event === 'plan_created' || event === 'planning_started' || event === 'plan_approved' || event === 'planning_complete') return '#0066cc';

  // Quality judge events
  if (event.startsWith('quality_')) return '#3498db';

  // Memory events
  if (event === 'memory_write' || event === 'aggregation_complete') return '#9b59b6';

  // Image analysis events
  if (event.startsWith('image_')) return '#8e44ad';

  // Document processing events
  if (event.startsWith('file_') || event.startsWith('document_') || event === 'all_files_processed' || event === 'context_s3_read') return '#e67e22';

  return '#e67e22';
}
