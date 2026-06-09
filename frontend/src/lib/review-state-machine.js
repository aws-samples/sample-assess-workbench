// =============================================================================
// Review flow state machine — pure logic, zero Preact imports.
// Handles all durable state transitions for the live review visualization.
//
// Visual/transient state (activeFlows, simProgress, orchProgress) is derived
// by useFlowVisuals from the durable state produced here.
// =============================================================================

import { fmtTokens } from './format-utils.js';

const DEFAULT_PIPELINE = [];

export function buildPipelineFromPlan(plan) {
  if (!plan || !plan.groups) return DEFAULT_PIPELINE;
  return plan.groups.map(group => ({
    id: group.group_id,
    type: group.agents.length > 1 ? 'parallel' : 'task',
    agents: group.agents.map(a => a.agent_type),
    label: group.label,
  }));
}

// --- Append event to log (capped at 100) ---
function appendEvent(events, event, detail, ts) {
  const next = [...events, { event, detail, ts: ts || new Date().toISOString() }];
  return next.length > 100 ? next.slice(-100) : next;
}

// =============================================================================
// Initial state
// =============================================================================

export const INITIAL_STATE = {
  phase: 'idle',
  nodeStates: {},
  statusLabel: '',
  events: [],
  pipeline: [],
  reviewPlan: null,
  agentMetrics: {},
  reviewMetrics: null,
  docFileEvents: { files: [], summary: null },
  imageEvents: { images: [], summary: null },
  qualityScores: {},
  coachState: {},
  toolCalls: {},
};

// =============================================================================
// Reducer — single source of truth for durable visualization state
// =============================================================================

export function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { ...INITIAL_STATE, phase: action.phase || 'idle' };

    case 'SET_PHASE':
      return { ...state, phase: action.phase };

    case 'SET_STATUS':
      return { ...state, statusLabel: action.label };

    case 'SET_PLAN': {
      const plan = action.plan;
      const pipeline = buildPipelineFromPlan(plan);
      return { ...state, reviewPlan: plan, pipeline };
    }

    case 'SET_ERROR':
      return { ...state, phase: 'error', statusLabel: action.label || 'An error occurred' };

    case 'LOAD_PREVIEW': {
      const plan = action.plan;
      return {
        ...state,
        phase: 'preview',
        reviewPlan: plan,
        pipeline: buildPipelineFromPlan(plan),
        nodeStates: { ...state.nodeStates, document_processing: 'done', s3: 'done', registry: 'done' },
        statusLabel: 'Review plan ready — approve to start',
      };
    }

    case 'EVENT': {
      const { event, detail, agentsMap, ts } = action;
      const s = { ...state, events: appendEvent(state.events, event, detail, ts) };
      return reduceEvent(s, event, detail, agentsMap || {});
    }

    default:
      return state;
  }
}

// =============================================================================
// Event-driven state transitions — durable state only.
// No activeFlows, simProgress, orchProgress — those are derived by
// useFlowVisuals from the event stream and nodeStates.
// =============================================================================

function reduceEvent(state, event, detail, ag) {
  // Terminal state guard — once a review is failed or complete, don't let
  // subsequent events (e.g., aggregation_complete arriving after review_aborted)
  // overwrite the status. Only allow events that are themselves terminal
  // transitions (workflow_failed, review_complete) to pass through, so the
  // event log still captures them.
  if (state.phase === 'failed' || state.phase === 'complete') {
    return state;
  }

  switch (event) {
    case 'document_processing_started':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, document_processing: 'active', s3: 'active' },
        statusLabel: `Processing ${detail.total_files} file${detail.total_files !== 1 ? 's' : ''}…`,
        docFileEvents: { files: [], summary: null },
      };

    case 'file_processing_started':
      return {
        ...state,
        docFileEvents: {
          ...state.docFileEvents,
          files: [...(state.docFileEvents?.files || []), { filename: detail.filename, type: detail.file_type, done: false, pages: 0, images: 0 }],
        },
        statusLabel: `Processing ${detail.filename}…`,
      };

    case 'file_text_extracted':
      return {
        ...state,
        docFileEvents: {
          ...state.docFileEvents,
          files: (state.docFileEvents?.files || []).map(f =>
            f.filename === detail.filename ? { ...f, done: true, pages: detail.pages, images: detail.images } : f
          ),
        },
        statusLabel: `${detail.filename}: ${detail.pages > 0 ? detail.pages + ' pages' : detail.size_kb + ' KB'}`,
      };

    case 'all_files_processed':
      return {
        ...state,
        docFileEvents: { ...state.docFileEvents, summary: { total_files: detail.total_files, total_pages: detail.total_pages, total_images: detail.total_images } },
        nodeStates: { ...state.nodeStates, document_processing: 'done', s3: 'done' },
        statusLabel: `${detail.total_files} files processed (${detail.combined_size_kb} KB)`,
      };

    case 'document_loaded': {
      const nodeStates = { ...state.nodeStates, orchestrator: 'active', registry: 'active' };
      if (nodeStates.document_processing !== 'done') nodeStates.document_processing = 'done';
      return {
        ...state,
        nodeStates,
        statusLabel: `Document loaded (${detail.size_kb} KB) — loading agents…`,
      };
    }

    case 'registry_loaded':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, registry: 'done' },
        statusLabel: `${detail.agent_count} agents loaded — designing review plan…`,
      };

    case 'planning_started':
      return { ...state, statusLabel: `AI planner thinking (${detail.model_id?.split('.').pop() || 'model'})…` };

    case 'planning_complete': {
      const durationSuffix = detail.planning_duration_ms ? ` in ${(detail.planning_duration_ms / 1000).toFixed(1)}s` : '';
      return { ...state, statusLabel: `Plan ready${durationSuffix} — storing…` };
    }

    case 'context_s3_read':
      return { ...state, statusLabel: 'Context document loaded' };

    case 'image_analysis_started':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, image_analysis: 'active' },
        statusLabel: `Analyzing ${detail.total_images} image${detail.total_images !== 1 ? 's' : ''}…`,
        imageEvents: { images: [], summary: null },
      };

    case 'image_triage_started':
      return { ...state, statusLabel: `Classifying image ${detail.index}/${detail.total}…` };

    case 'image_classified':
      return {
        ...state,
        imageEvents: {
          ...state.imageEvents,
          images: [...(state.imageEvents?.images || []), {
            filename: detail.filename, page_num: detail.page_num,
            category: detail.category, relevant: detail.relevant,
            brief_description: detail.brief_description,
            status: detail.relevant ? 'analyzing' : 'skipped',
            triage_tokens: detail.triage_tokens,
          }],
        },
        statusLabel: detail.relevant
          ? `${detail.brief_description || detail.category} — analyzing…`
          : `${detail.brief_description || detail.category} — skipped`,
      };

    case 'image_analysis_in_progress':
      return { ...state, statusLabel: `Analyzing ${detail.category?.replace(/_/g, ' ')} (p${detail.page_num})…` };

    case 'image_analyzed':
      return {
        ...state,
        imageEvents: {
          ...state.imageEvents,
          images: (state.imageEvents?.images || []).map(img =>
            img.page_num === detail.page_num && img.filename === detail.filename
              ? { ...img, status: 'analyzed', analysis_tokens: detail.analysis_tokens, diagram_type: detail.diagram_type }
              : img
          ),
        },
        statusLabel: `${detail.diagram_type?.replace(/_/g, ' ') || 'Diagram'}: ${detail.component_count} components, ${detail.connection_count} connections`,
      };

    case 'image_skipped':
      return state;

    case 'image_analysis_completed':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, image_analysis: 'done' },
        imageEvents: { ...state.imageEvents, summary: { analyzed: detail.analyzed, skipped: detail.skipped, total_tokens: detail.total_tokens } },
        statusLabel: `Images: ${detail.analyzed} analyzed, ${detail.skipped} skipped — ${fmtTokens(detail.total_tokens)} tokens`,
      };

    case 'plan_created': {
      const plan = detail.plan || detail;
      const pipeline = buildPipelineFromPlan(plan);
      const durationSuffix = detail.planning_duration_ms ? ` (${(detail.planning_duration_ms / 1000).toFixed(1)}s)` : '';
      return {
        ...state,
        phase: 'preview',
        reviewPlan: plan,
        pipeline,
        nodeStates: { ...state.nodeStates, document_processing: 'done', s3: 'done', registry: 'done' },
        statusLabel: detail.requires_approval === false
          ? 'AI planned review — auto-approving…'
          : `Review plan ready${durationSuffix} — approve to start`,
      };
    }

    case 'plan_approved': {
      const approvedPlan = detail.plan || state.reviewPlan;
      const pipeline = detail.plan ? buildPipelineFromPlan(approvedPlan) : state.pipeline;
      return {
        ...state,
        phase: 'executing',
        reviewPlan: approvedPlan,
        pipeline,
        nodeStates: { ...state.nodeStates, orchestrator: 'active' },
        statusLabel: 'Plan approved — executing review…',
      };
    }

    case 'agent_started': {
      const label = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      return {
        ...state,
        nodeStates: { ...state.nodeStates, [detail.agent]: 'active' },
        statusLabel: detail.iteration > 0
          ? `${label} retry #${detail.iteration + 1} (coach feedback)`
          : `${label} review started`,
      };
    }

    case 'agent_completed': {
      const label = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      const updatedNodes = { ...state.nodeStates };
      const planAgent = state.reviewPlan?.groups
        ?.flatMap(g => g.agents)
        ?.find(a => a.agent_type === detail.agent);
      if (planAgent?.judge?.enabled) {
        updatedNodes[`coach_${detail.agent}`] = 'active';
      } else {
        updatedNodes[detail.agent] = 'done';
      }
      return {
        ...state,
        nodeStates: updatedNodes,
        agentMetrics: detail.metrics ? { ...state.agentMetrics, [detail.agent]: detail.metrics } : state.agentMetrics,
        statusLabel: `${label}: ${detail.finding_count} findings${detail.iteration > 0 ? ` (iteration ${detail.iteration + 1})` : ''}`,
      };
    }

    case 'agent_recovered': {
      const label = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      return {
        ...state,
        nodeStates: { ...state.nodeStates, [detail.agent]: 'warning' },
        statusLabel: `${label}: recovered with ${detail.finding_count} findings (${detail.status_reason || 'prior iteration'})`,
      };
    }

    case 'agent_failed': {
      const label = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      return {
        ...state,
        nodeStates: { ...state.nodeStates, [detail.agent]: 'error' },
        statusLabel: `${label}: failed — ${detail.status_reason || 'unknown error'}`,
      };
    }

    case 'judge_started': {
      const coachId = `coach_${detail.agent}`;
      const agentLabel = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      return {
        ...state,
        nodeStates: { ...state.nodeStates, [coachId]: 'active' },
        statusLabel: detail.mode === 'coach'
          ? `📋 ${agentLabel} coach iteration ${(detail.iteration || 0) + 1}…`
          : `📋 Evaluating ${agentLabel}…`,
      };
    }

    case 'judge_evaluated': {
      const coachId = `coach_${detail.agent}`;
      const agentLabel = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      const score = typeof detail.score === 'number' ? detail.score : 0;
      const coachEntry = { iteration: (detail.iteration || 0) + 1, status: detail.quality_met ? 'pass' : 'fail', score };
      const agentNodeState = detail.quality_met ? 'done' : state.nodeStates[detail.agent];
      const coachNodeState = detail.quality_met ? 'done' : 'active';
      return {
        ...state,
        nodeStates: { ...state.nodeStates, [detail.agent]: agentNodeState, [coachId]: coachNodeState },
        coachState: { ...state.coachState, [detail.agent]: coachEntry },
        statusLabel: detail.quality_met
          ? `📋 ${agentLabel} passed quality (${score.toFixed(2)}) ✓`
          : `📋 ${agentLabel} needs improvement (${score.toFixed(2)}) — retrying…`,
      };
    }

    case 'agent_error':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, [detail.agent]: 'error' },
        statusLabel: `${ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent} failed: ${detail.error}`,
      };

    case 'agent_memory_write': {
      const label = ag[detail.agent]?.label || ag[detail.agent]?.display_name || detail.agent;
      return {
        ...state,
        nodeStates: { ...state.nodeStates, memory: 'active' },
        statusLabel: `${label}: ${detail.records} findings written to memory`,
      };
    }

    case 'agent_tool_calls': {
      const calls = detail.tool_calls || [];
      const prev = state.toolCalls[detail.agent];
      const prevTotal = prev ? prev.total : 0;
      const prevTools = prev ? { ...prev.tools } : {};
      for (const tc of calls) {
        prevTools[tc.tool] = (prevTools[tc.tool] || 0) + 1;
      }
      return {
        ...state,
        toolCalls: { ...state.toolCalls, [detail.agent]: { total: prevTotal + calls.length, tools: prevTools } },
      };
    }

    case 'memory_write':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, memory: 'active' },
        statusLabel: `Storing ${detail.records} findings to memory`,
      };

    case 'aggregation_complete':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, memory: 'done' },
        statusLabel: `Aggregated ${detail.total_findings} findings — evaluating quality…`,
      };

    case 'quality_evaluation_started':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, quality_judge: 'active' },
        statusLabel: 'Evaluating quality…',
      };

    case 'quality_score':
      return { ...state, qualityScores: { ...state.qualityScores, [detail.agent]: detail.overall } };

    case 'quality_evaluation_complete':
      return { ...state, nodeStates: { ...state.nodeStates, quality_judge: 'done' } };

    case 'quality_evaluation_failed':
      return {
        ...state,
        nodeStates: { ...state.nodeStates, quality_judge: 'error' },
        statusLabel: `Quality evaluation failed: ${detail.error || 'unknown'}`,
      };

    case 'review_complete': {
      const nodeStates = { ...state.nodeStates, orchestrator: 'done', memory: 'done' };
      Object.keys(nodeStates).forEach(k => { if (nodeStates[k] === 'active') nodeStates[k] = 'done'; });
      return {
        ...state,
        phase: 'complete',
        nodeStates,
        reviewMetrics: detail.metrics || state.reviewMetrics,
        statusLabel: `Complete — ${detail.total_findings} findings${detail.duration_ms ? ` in ${(detail.duration_ms / 1000).toFixed(1)}s` : ''}`,
      };
    }

    case 'review_aborted': {
      const nodeStates = { ...state.nodeStates, orchestrator: 'error' };
      Object.keys(nodeStates).forEach(k => { if (nodeStates[k] === 'active') nodeStates[k] = 'error'; });
      const failed = detail.failed_agents?.join(', ') || 'unknown';
      return {
        ...state,
        phase: 'failed',
        nodeStates,
        statusLabel: `Review aborted — ${failed} failed. Partial results preserved.`,
      };
    }

    case 'workflow_failed': {
      const nodeStates = { ...state.nodeStates, orchestrator: 'error' };
      Object.keys(nodeStates).forEach(k => { if (nodeStates[k] === 'active') nodeStates[k] = 'error'; });
      return {
        ...state,
        phase: 'failed',
        nodeStates,
        statusLabel: `Failed: ${detail.error || 'unknown error'}`,
      };
    }

    case 'workflow_completed_with_warnings': {
      const nodeStates = { ...state.nodeStates, orchestrator: 'done', memory: 'done' };
      Object.keys(nodeStates).forEach(k => { if (nodeStates[k] === 'active') nodeStates[k] = 'done'; });
      return {
        ...state,
        phase: 'complete',
        nodeStates,
        warnings: detail.warning || 'Post-completion step failed',
        statusLabel: `Complete (with warnings) — ${detail.warning || 'bookkeeping error'}`,
      };
    }

    default:
      return state;
  }
}
