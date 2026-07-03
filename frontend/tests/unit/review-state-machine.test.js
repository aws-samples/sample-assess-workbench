// =============================================================================
// Reducer unit tests — durable state transitions only.
// These test the pure event→state logic. Transient visual fields (activeFlows,
// simProgress, orchProgress) are asserted only where they affect correctness
// (e.g. phase transitions). They'll be removed from the reducer in Phase 4.
// =============================================================================

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { reducer, INITIAL_STATE, buildPipelineFromPlan } from '../../src/lib/review-state-machine.js';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Dispatch an EVENT action through the reducer. */
function dispatch(state, event, detail = {}, agentsMap = {}) {
  return reducer(state, { type: 'EVENT', event, detail, agentsMap, ts: new Date().toISOString() });
}

/** A minimal plan with two parallel agents + one sequential agent, all coach-enabled. */
const TEST_PLAN = {
  groups: [
    {
      group_id: 'initial', label: 'Initial Reviews', execution: 'parallel',
      agents: [
        { agent_type: 'architecture', depth: 'thorough', focus_areas: [], depends_on: [], prompt_addendum: '', judge: { enabled: true, max_iterations: 3, quality_threshold: 0.8 } },
        { agent_type: 'security', depth: 'thorough', focus_areas: [], depends_on: [], prompt_addendum: '', judge: { enabled: true, max_iterations: 3, quality_threshold: 0.8 } },
      ],
    },
    {
      group_id: 'risk', label: 'Risk Assessment', execution: 'sequential',
      agents: [
        { agent_type: 'risk', depth: 'thorough', focus_areas: [], depends_on: ['architecture', 'security'], prompt_addendum: '', judge: { enabled: true, max_iterations: 3, quality_threshold: 0.8 } },
      ],
    },
  ],
};

const AGENTS_MAP = {
  architecture: { label: 'Architecture', icon: '🏗️', color: '#0066cc' },
  security: { label: 'Security', icon: '🔒', color: '#e74c3c' },
  risk: { label: 'Risk', icon: '⚠️', color: '#f39c12' },
};

// ---------------------------------------------------------------------------
// buildPipelineFromPlan
// ---------------------------------------------------------------------------

describe('buildPipelineFromPlan', () => {
  it('converts plan groups to pipeline stages', () => {
    const pipeline = buildPipelineFromPlan(TEST_PLAN);
    expect(pipeline).toHaveLength(2);
    expect(pipeline[0].agents).toEqual(['architecture', 'security']);
    expect(pipeline[0].type).toBe('parallel');
    expect(pipeline[1].agents).toEqual(['risk']);
    expect(pipeline[1].type).toBe('task');
  });

  it('returns empty array for null/missing plan', () => {
    expect(buildPipelineFromPlan(null)).toEqual([]);
    expect(buildPipelineFromPlan({})).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Full review lifecycle
// ---------------------------------------------------------------------------

describe('full review lifecycle', () => {
  let state;

  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    state = INITIAL_STATE;
  });

  it('walks through document processing → agents → completion', () => {
    // Document processing
    state = dispatch(state, 'document_processing_started', { total_files: 2 });
    expect(state.nodeStates.document_processing).toBe('active');
    expect(state.nodeStates.s3).toBe('active');
    expect(state.phase).toBe('idle');

    state = dispatch(state, 'file_processing_started', { filename: 'spec.pdf', file_type: 'pdf', index: 1, total_files: 2 });
    expect(state.docFileEvents.files).toHaveLength(1);
    expect(state.docFileEvents.files[0].filename).toBe('spec.pdf');

    state = dispatch(state, 'file_text_extracted', { filename: 'spec.pdf', pages: 10, size_kb: 120, index: 1, total_files: 2 });
    expect(state.docFileEvents.files[0].done).toBe(true);
    expect(state.docFileEvents.files[0].pages).toBe(10);

    state = dispatch(state, 'all_files_processed', { total_files: 2, total_pages: 10, total_images: 0, combined_size_kb: 124 });
    expect(state.nodeStates.document_processing).toBe('done');
    expect(state.nodeStates.s3).toBe('done');
    expect(state.docFileEvents.summary.total_files).toBe(2);

    state = dispatch(state, 'document_loaded', { size_kb: 124, total_files: 2 });
    expect(state.nodeStates.orchestrator).toBe('active');

    state = dispatch(state, 'registry_loaded', { agent_count: 3 });
    expect(state.nodeStates.registry).toBe('done');

    // Plan
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: false });
    expect(state.phase).toBe('preview');
    expect(state.pipeline).toHaveLength(2);
    expect(state.reviewPlan).toBe(TEST_PLAN);

    state = dispatch(state, 'plan_approved', { auto: true });
    expect(state.phase).toBe('executing');

    // Agent execution
    state = dispatch(state, 'agent_started', { agent: 'architecture', iteration: 0, max_iterations: 3 }, AGENTS_MAP);
    expect(state.nodeStates.architecture).toBe('active');

    state = dispatch(state, 'agent_completed', { agent: 'architecture', finding_count: 8, iteration: 0, metrics: { total_tokens: 14200, cycle_count: 2 } }, AGENTS_MAP);
    // Coach is enabled, so agent stays active until judge confirms
    expect(state.nodeStates.coach_architecture).toBe('active');
    expect(state.agentMetrics.architecture.total_tokens).toBe(14200);

    state = dispatch(state, 'judge_evaluated', { agent: 'architecture', score: 0.87, quality_met: true, iteration: 0 }, AGENTS_MAP);
    expect(state.nodeStates.architecture).toBe('done');
    expect(state.coachState.architecture.status).toBe('pass');
    expect(state.coachState.architecture.score).toBe(0.87);

    // Security + risk (abbreviated)
    state = dispatch(state, 'agent_started', { agent: 'security', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_completed', { agent: 'security', finding_count: 9, iteration: 0, metrics: { total_tokens: 12400, cycle_count: 2 } }, AGENTS_MAP);
    state = dispatch(state, 'judge_evaluated', { agent: 'security', score: 0.84, quality_met: true, iteration: 0 }, AGENTS_MAP);
    expect(state.nodeStates.security).toBe('done');

    state = dispatch(state, 'agent_started', { agent: 'risk', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_completed', { agent: 'risk', finding_count: 5, iteration: 0, metrics: { total_tokens: 11400, cycle_count: 2 } }, AGENTS_MAP);
    state = dispatch(state, 'judge_evaluated', { agent: 'risk', score: 0.88, quality_met: true, iteration: 0 }, AGENTS_MAP);

    // Post-execution
    state = dispatch(state, 'memory_write', { records: 22 });
    expect(state.nodeStates.memory).toBe('active');

    state = dispatch(state, 'aggregation_complete', { total_findings: 22 });
    expect(state.nodeStates.memory).toBe('done');

    state = dispatch(state, 'quality_evaluation_started', { agent_count: 3 });
    expect(state.nodeStates.quality_judge).toBe('active');

    state = dispatch(state, 'quality_score', { agent: 'architecture', overall: 0.85 });
    state = dispatch(state, 'quality_score', { agent: 'security', overall: 0.78 });
    state = dispatch(state, 'quality_score', { agent: 'risk', overall: 0.91 });
    expect(state.qualityScores).toEqual({ architecture: 0.85, security: 0.78, risk: 0.91 });

    state = dispatch(state, 'quality_evaluation_complete', { scores: { architecture: 0.85, security: 0.78, risk: 0.91 } });
    expect(state.nodeStates.quality_judge).toBe('done');

    // Completion
    state = dispatch(state, 'review_complete', { total_findings: 22, duration_ms: 34200, metrics: { total_tokens: 68500 } });
    expect(state.phase).toBe('complete');
    expect(state.nodeStates.orchestrator).toBe('done');
    expect(state.reviewMetrics.total_tokens).toBe(68500);

    // All events recorded
    expect(state.events.length).toBeGreaterThanOrEqual(20);
  });
});

// ---------------------------------------------------------------------------
// Coach loop — reject then accept
// ---------------------------------------------------------------------------

describe('coach loop', () => {
  let state;

  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    state = INITIAL_STATE;
    // Fast-forward to executing with a plan
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: false });
    state = dispatch(state, 'plan_approved', { auto: true });
  });

  it('handles reject → retry → accept cycle', () => {
    // First attempt
    state = dispatch(state, 'agent_started', { agent: 'security', iteration: 0, max_iterations: 3 }, AGENTS_MAP);
    state = dispatch(state, 'agent_completed', { agent: 'security', finding_count: 9, iteration: 0, metrics: { total_tokens: 12400, cycle_count: 2 } }, AGENTS_MAP);

    // Judge rejects
    state = dispatch(state, 'judge_evaluated', { agent: 'security', score: 0.62, quality_met: false, iteration: 0, critique_summary: 'Missing OWASP mappings' }, AGENTS_MAP);
    expect(state.coachState.security.status).toBe('fail');
    expect(state.coachState.security.score).toBe(0.62);
    expect(state.coachState.security.iteration).toBe(1);
    expect(state.nodeStates.security).not.toBe('done');

    // Retry
    state = dispatch(state, 'agent_started', { agent: 'security', iteration: 1, max_iterations: 3 }, AGENTS_MAP);
    expect(state.nodeStates.security).toBe('active');

    state = dispatch(state, 'agent_completed', { agent: 'security', finding_count: 12, iteration: 1, metrics: { total_tokens: 18600, cycle_count: 3 } }, AGENTS_MAP);

    // Judge accepts
    state = dispatch(state, 'judge_evaluated', { agent: 'security', score: 0.84, quality_met: true, iteration: 1 }, AGENTS_MAP);
    expect(state.coachState.security.status).toBe('pass');
    expect(state.coachState.security.score).toBe(0.84);
    expect(state.coachState.security.iteration).toBe(2);
    expect(state.nodeStates.security).toBe('done');
    expect(state.nodeStates.coach_security).toBe('done');
  });
});

// ---------------------------------------------------------------------------
// Terminal states
// ---------------------------------------------------------------------------

describe('terminal states', () => {
  let state;

  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    state = INITIAL_STATE;
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: false });
    state = dispatch(state, 'plan_approved', { auto: true });
    state = dispatch(state, 'agent_started', { agent: 'architecture', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_started', { agent: 'security', iteration: 0 }, AGENTS_MAP);
  });

  it('review_complete sets all active nodes to done', () => {
    state = dispatch(state, 'review_complete', { total_findings: 10, duration_ms: 5000 });
    expect(state.phase).toBe('complete');
    expect(state.nodeStates.architecture).toBe('done');
    expect(state.nodeStates.security).toBe('done');
    expect(state.nodeStates.orchestrator).toBe('done');
  });

  it('workflow_failed sets active nodes to error', () => {
    state = dispatch(state, 'workflow_failed', { error: 'Lambda timeout' });
    expect(state.phase).toBe('failed');
    expect(state.nodeStates.architecture).toBe('error');
    expect(state.nodeStates.security).toBe('error');
    expect(state.nodeStates.orchestrator).toBe('error');
  });

  it('review_aborted sets active nodes to error', () => {
    state = dispatch(state, 'review_aborted', { failed_agents: ['security'], message: 'Aborted' });
    expect(state.phase).toBe('failed');
    expect(state.nodeStates.architecture).toBe('error');
    expect(state.nodeStates.security).toBe('error');
    expect(state.nodeStates.orchestrator).toBe('error');
  });

  it('workflow_completed_with_warnings sets phase to complete with warnings', () => {
    state = dispatch(state, 'workflow_completed_with_warnings', { warning: 'StoreResults failed: DynamoDB timeout' });
    expect(state.phase).toBe('complete');
    expect(state.warnings).toBe('StoreResults failed: DynamoDB timeout');
    expect(state.nodeStates.architecture).toBe('done');
    expect(state.nodeStates.security).toBe('done');
    expect(state.nodeStates.orchestrator).toBe('done');
    expect(state.statusLabel).toContain('with warnings');
  });
});

// ---------------------------------------------------------------------------
// Plan pipeline transitions
// ---------------------------------------------------------------------------

describe('plan transitions', () => {
  let state;

  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    state = INITIAL_STATE;
  });

  it('plan_created sets phase to preview and builds pipeline', () => {
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: true });
    expect(state.phase).toBe('preview');
    expect(state.pipeline).toHaveLength(2);
    expect(state.reviewPlan).toBe(TEST_PLAN);
    expect(state.nodeStates.document_processing).toBe('done');
    expect(state.nodeStates.s3).toBe('done');
    expect(state.nodeStates.registry).toBe('done');
  });

  it('plan_approved transitions to executing', () => {
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: true });
    state = dispatch(state, 'plan_approved', { auto: false });
    expect(state.phase).toBe('executing');
    expect(state.nodeStates.orchestrator).toBe('active');
  });

  it('plan_approved with custom plan overwrites the original', () => {
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: true });

    const customPlan = {
      groups: [{ group_id: 'only', label: 'Only', execution: 'parallel', agents: [{ agent_type: 'security', judge: { enabled: false } }] }],
    };
    state = dispatch(state, 'plan_approved', { auto: false, plan: customPlan });
    expect(state.pipeline).toHaveLength(1);
    expect(state.pipeline[0].agents).toEqual(['security']);
    expect(state.reviewPlan).toBe(customPlan);
  });
});

// ---------------------------------------------------------------------------
// Image analysis events
// ---------------------------------------------------------------------------

describe('image analysis', () => {
  let state;

  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    state = INITIAL_STATE;
    state = dispatch(state, 'document_processing_started', { total_files: 1 });
    state = dispatch(state, 'all_files_processed', { total_files: 1, total_pages: 5, total_images: 2, combined_size_kb: 100 });
  });

  it('tracks image classification and analysis', () => {
    state = dispatch(state, 'image_analysis_started', { total_images: 2 });
    expect(state.nodeStates.image_analysis).toBe('active');
    expect(state.imageEvents.images).toEqual([]);

    state = dispatch(state, 'image_classified', { filename: 'doc.pdf', page_num: 1, category: 'logo', relevant: false, brief_description: 'Logo' });
    expect(state.imageEvents.images).toHaveLength(1);
    expect(state.imageEvents.images[0].status).toBe('skipped');

    state = dispatch(state, 'image_classified', { filename: 'doc.pdf', page_num: 3, category: 'architecture_diagram', relevant: true, brief_description: 'AWS diagram' });
    expect(state.imageEvents.images).toHaveLength(2);
    expect(state.imageEvents.images[1].status).toBe('analyzing');

    state = dispatch(state, 'image_analyzed', { filename: 'doc.pdf', page_num: 3, diagram_type: 'architecture_diagram', component_count: 8, connection_count: 6, analysis_tokens: { input: 1200, output: 850 } });
    expect(state.imageEvents.images[1].status).toBe('analyzed');

    state = dispatch(state, 'image_analysis_completed', { analyzed: 1, skipped: 1, total_tokens: 2050 });
    expect(state.nodeStates.image_analysis).toBe('done');
    expect(state.imageEvents.summary).toEqual({ analyzed: 1, skipped: 1, total_tokens: 2050 });
  });
});

// ---------------------------------------------------------------------------
// Agent edge cases
// ---------------------------------------------------------------------------

describe('agent edge cases', () => {
  let state;

  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    state = INITIAL_STATE;
    // Plan with no coach for simpler assertions
    const noPlan = { groups: [{ group_id: 'g1', agents: [{ agent_type: 'architecture', judge: { enabled: false } }] }] };
    state = dispatch(state, 'plan_created', { plan: noPlan });
    state = dispatch(state, 'plan_approved', { auto: true });
  });

  it('agent_completed without coach sets node to done immediately', () => {
    state = dispatch(state, 'agent_started', { agent: 'architecture', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_completed', { agent: 'architecture', finding_count: 5, iteration: 0, metrics: { total_tokens: 10000, cycle_count: 1 } }, AGENTS_MAP);
    expect(state.nodeStates.architecture).toBe('done');
  });

  it('agent_recovered sets node to warning', () => {
    state = dispatch(state, 'agent_started', { agent: 'architecture', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_recovered', { agent: 'architecture', finding_count: 3, status_reason: 'prior iteration' }, AGENTS_MAP);
    expect(state.nodeStates.architecture).toBe('warning');
  });

  it('agent_failed sets node to error', () => {
    state = dispatch(state, 'agent_started', { agent: 'architecture', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_failed', { agent: 'architecture', status_reason: 'timeout' }, AGENTS_MAP);
    expect(state.nodeStates.architecture).toBe('error');
  });

  it('agent_error sets node to error', () => {
    state = dispatch(state, 'agent_started', { agent: 'architecture', iteration: 0 }, AGENTS_MAP);
    state = dispatch(state, 'agent_error', { agent: 'architecture', error: 'OOM' }, AGENTS_MAP);
    expect(state.nodeStates.architecture).toBe('error');
  });
});

// ---------------------------------------------------------------------------
// Quality evaluation failure
// ---------------------------------------------------------------------------

describe('quality evaluation', () => {
  it('quality_evaluation_failed sets quality_judge to error', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    let state = INITIAL_STATE;
    state = dispatch(state, 'quality_evaluation_started', { agent_count: 3 });
    expect(state.nodeStates.quality_judge).toBe('active');

    state = dispatch(state, 'quality_evaluation_failed', { error: 'model error' });
    expect(state.nodeStates.quality_judge).toBe('error');
  });
});

// ---------------------------------------------------------------------------
// Event log capping
// ---------------------------------------------------------------------------

describe('event log', () => {
  it('caps at 100 events', () => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
    let state = INITIAL_STATE;
    for (let i = 0; i < 110; i++) {
      state = dispatch(state, 'quality_score', { agent: `agent_${i}`, overall: 0.8 });
    }
    expect(state.events).toHaveLength(100);
    // Most recent event should be the last one dispatched
    expect(state.events[99].detail.agent).toBe('agent_109');
  });
});

// ---------------------------------------------------------------------------
// SET_ERROR action
// ---------------------------------------------------------------------------

describe('SET_ERROR', () => {
  it('sets phase to error with the provided label', () => {
    const state = reducer(INITIAL_STATE, { type: 'SET_ERROR', label: 'Review not found' });
    expect(state.phase).toBe('error');
    expect(state.statusLabel).toBe('Review not found');
  });

  it('defaults label when none provided', () => {
    const state = reducer(INITIAL_STATE, { type: 'SET_ERROR' });
    expect(state.phase).toBe('error');
    expect(state.statusLabel).toBe('An error occurred');
  });

  it('RESET from error phase returns to INITIAL_STATE', () => {
    let state = reducer(INITIAL_STATE, { type: 'SET_ERROR', label: 'Something broke' });
    expect(state.phase).toBe('error');
    state = reducer(state, { type: 'RESET' });
    expect(state.phase).toBe('idle');
    expect(state.events).toEqual([]);
    expect(state.nodeStates).toEqual({});
    expect(state.statusLabel).toBe('');
  });
});

// ---------------------------------------------------------------------------
// RESET action
// ---------------------------------------------------------------------------

describe('RESET', () => {
  it('returns to initial state with optional phase', () => {
    let state = dispatch(INITIAL_STATE, 'document_processing_started', { total_files: 1 });
    state = reducer(state, { type: 'RESET', phase: 'idle' });
    expect(state.phase).toBe('idle');
    expect(state.events).toEqual([]);
    expect(state.nodeStates).toEqual({});
    expect(state.pipeline).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Known issues — these assert CORRECT behavior that the current code fails.
// Marked with it.fails() so the suite stays green. When Phase 4 fixes these,
// the tests will start passing and vitest will flag the .fails() as unexpected
// passes — remove the .fails() marker at that point.
// ---------------------------------------------------------------------------

describe('known issues (fixed in Phase 4)', () => {
  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(1000000);
  });

  it('reducer is deterministic — same events produce same state regardless of wall-clock time', () => {
    // Previously, plan_approved stored Date.now() in orchProgress.lastEventAt.
    // Phase 4 removed orchProgress from the reducer entirely.
    let state = INITIAL_STATE;
    state = dispatch(state, 'plan_created', { plan: TEST_PLAN, requires_approval: false });
    Date.now.mockReturnValue(2000000);
    const state1 = dispatch(state, 'plan_approved', { auto: true });

    let state2 = INITIAL_STATE;
    state2 = dispatch(state2, 'plan_created', { plan: TEST_PLAN, requires_approval: false });
    Date.now.mockReturnValue(9999999);
    const state2b = dispatch(state2, 'plan_approved', { auto: true });

    // With orchProgress removed, these states should be identical
    // (events array timestamps differ, but the durable fields match)
    expect(state1.phase).toBe(state2b.phase);
    expect(state1.nodeStates).toEqual(state2b.nodeStates);
    expect(state1.pipeline).toEqual(state2b.pipeline);
    expect(state1.statusLabel).toBe(state2b.statusLabel);
  });

  it('reducer is deterministic — no simProgress means no Date.now dependency', () => {
    // Previously, startSim() stored Date.now() in simProgress[id].start.
    // Phase 4 removed simProgress from the reducer entirely.
    Date.now.mockReturnValue(5000000);
    const state1 = dispatch(INITIAL_STATE, 'document_processing_started', { total_files: 1 });

    Date.now.mockReturnValue(8000000);
    const state2 = dispatch(INITIAL_STATE, 'document_processing_started', { total_files: 1 });

    // Durable state should be identical regardless of wall-clock time
    expect(state1.nodeStates).toEqual(state2.nodeStates);
    expect(state1.statusLabel).toBe(state2.statusLabel);
    expect(state1.phase).toBe(state2.phase);
    // simProgress no longer exists in state
    expect(state1.simProgress).toBeUndefined();
    expect(state2.simProgress).toBeUndefined();
  });
});
