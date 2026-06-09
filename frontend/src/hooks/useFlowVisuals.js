// =============================================================================
// useFlowVisuals — derives visual state from durable reducer state + time.
//
// Computes activeFlows and per-node progress values that were previously
// managed inside the reducer. These are transient, time-dependent values
// that don't belong in the durable state machine.
// =============================================================================

import { useState, useEffect, useMemo } from 'preact/hooks';
import { agentProgress, orchestratorProgress, DURATION_ESTIMATES } from '../lib/progress-model.js';

const FLOW_TTL_MS = 2000;
const TICK_INTERVAL_MS = 200;

/**
 * Map from event type to the flow arrows it implies.
 * Each entry returns an array of { from, to } given the event detail.
 */
const EVENT_FLOW_MAP = {
  document_processing_started: () => [{ from: 'document_processing', to: 's3' }],
  all_files_processed: (d) => d.total_images > 0
    ? [{ from: 'document_processing', to: 'image_analysis' }]
    : [{ from: 'document_processing', to: 'orchestrator' }],
  document_loaded: (d, state) => {
    const hasImg = d.images_analyzed > 0 ||
      state.nodeStates.image_analysis === 'active' ||
      state.nodeStates.image_analysis === 'done';
    const source = hasImg ? 'image_analysis' : 'document_processing';
    return [{ from: source, to: 'orchestrator' }, { from: 'registry', to: 'orchestrator' }];
  },
  image_analysis_started: () => [{ from: 'document_processing', to: 'image_analysis' }],
  image_analysis_completed: () => [{ from: 'image_analysis', to: 'orchestrator' }],
  agent_started: (d) => [{ from: 'orchestrator', to: d.agent }],
  agent_completed: (d) => [{ from: d.agent, to: 'orchestrator' }],
  agent_recovered: (d) => [{ from: d.agent, to: 'orchestrator' }],
  agent_failed: () => [],
  judge_started: (d) => d.mode === 'coach' ? [{ from: d.agent, to: `coach_${d.agent}` }] : [],
  judge_evaluated: (d) => [{ from: d.agent, to: `coach_${d.agent}` }],
  memory_write: () => [{ from: 'orchestrator', to: 'memory' }],
  agent_memory_write: (d) => [{ from: d.agent, to: 'memory' }],
  agent_tool_calls: (d) => [{ from: d.agent, to: 'memory' }],
  quality_evaluation_started: () => [{ from: 'orchestrator', to: 'quality_judge' }],
};

/**
 * Derive active flow arrows from recent events.
 * A flow is "active" if the event that created it is within FLOW_TTL_MS of now.
 */
function deriveActiveFlows(events, state, now) {
  const flows = [];
  const seen = new Set();

  // Walk events in reverse (most recent first) — only look at recent ones
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    const evTime = new Date(ev.ts).getTime();
    if (now - evTime > FLOW_TTL_MS) break;

    const mapper = EVENT_FLOW_MAP[ev.event];
    if (!mapper) continue;

    const arrows = mapper(ev.detail || {}, state);
    for (const arrow of arrows) {
      const key = `${arrow.from}->${arrow.to}`;
      if (!seen.has(key)) {
        seen.add(key);
        flows.push(arrow);
      }
    }
  }

  return flows;
}

/**
 * Derive orchestrator progress from events.
 * Mirrors the weight logic that was previously in the reducer.
 */
function deriveOrchProgress(events, reviewPlan) {
  let completedWeight = 0;
  let totalWeight = 0;
  let lastEventAt = null;

  // Compute totalWeight from the plan (same logic as plan_approved in reducer)
  const pipeline = reviewPlan?.groups || [];
  for (const group of pipeline) {
    for (const agent of group.agents) {
      totalWeight += 10; // agent review
      if (agent.judge?.enabled) totalWeight += 2; // coach evaluation
    }
  }
  totalWeight += 1; // memory write
  totalWeight += 2; // quality evaluation

  // Walk events to accumulate completed weight
  for (const ev of events) {
    const evTime = new Date(ev.ts).getTime();
    switch (ev.event) {
      case 'agent_completed':
      case 'agent_recovered':
      case 'agent_failed':
        completedWeight += 10;
        lastEventAt = evTime;
        break;
      case 'judge_evaluated':
        completedWeight += 2;
        lastEventAt = evTime;
        break;
      case 'memory_write':
        completedWeight += 1;
        lastEventAt = evTime;
        break;
      case 'quality_evaluation_complete':
        completedWeight += 2;
        lastEventAt = evTime;
        break;
    }
  }

  return { completedWeight, totalWeight, lastEventAt };
}

/**
 * Find the timestamp when a node became active by scanning events.
 * Returns ms timestamp or null.
 */
function findNodeStartTime(events, nodeId) {
  // Walk in reverse to find the most recent activation
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i];
    switch (ev.event) {
      case 'document_processing_started':
        if (nodeId === 'document_processing' || nodeId === 's3') return new Date(ev.ts).getTime();
        break;
      case 'image_analysis_started':
        if (nodeId === 'image_analysis') return new Date(ev.ts).getTime();
        break;
      case 'document_loaded':
        if (nodeId === 'orchestrator') return new Date(ev.ts).getTime();
        break;
      case 'agent_started':
        if (ev.detail?.agent === nodeId) return new Date(ev.ts).getTime();
        break;
      case 'memory_write':
        if (nodeId === 'memory') return new Date(ev.ts).getTime();
        break;
      case 'quality_evaluation_started':
        if (nodeId === 'quality_judge') return new Date(ev.ts).getTime();
        break;
      case 'plan_approved':
        if (nodeId === 'orchestrator') return new Date(ev.ts).getTime();
        break;
    }
  }
  return null;
}

/**
 * Compute progress for a single node.
 */
function getNodeProgress(nodeId, nodeState, events, reviewPlan, phase, now) {
  if (nodeState === 'done' || nodeState === 'error' || nodeState === 'warning') return 1;
  if (nodeState !== 'active') return 0;

  // Orchestrator uses different strategies depending on phase:
  // - loading: time-based curve (planning is a single long-running operation)
  // - executing: milestone-based (progress advances per agent completion)
  if (nodeId === 'orchestrator') {
    if (phase === 'loading') {
      const startedAt = findNodeStartTime(events, nodeId);
      if (!startedAt) return 0;
      return agentProgress(startedAt, now, DURATION_ESTIMATES.orchestrator || 15000);
    }
    const orch = deriveOrchProgress(events, reviewPlan);
    return orchestratorProgress(orch.completedWeight, orch.totalWeight, orch.lastEventAt, now);
  }

  // Everything else uses the exponential curve
  const startedAt = findNodeStartTime(events, nodeId);
  if (!startedAt) return 0;
  const duration = DURATION_ESTIMATES[nodeId] || 30000;
  return agentProgress(startedAt, now, duration);
}

/**
 * Hook that derives all visual state from the durable reducer state.
 *
 * @param {object} state - Durable reducer state
 * @returns {{ activeFlows: Array, getNodeProgress: (nodeId: string) => number }}
 */
export function useFlowVisuals(state) {
  const { events, nodeStates, reviewPlan, phase } = state;
  const [now, setNow] = useState(Date.now);

  // Tick while any node is active
  const hasActiveNodes = useMemo(
    () => Object.values(nodeStates).some(s => s === 'active'),
    [nodeStates],
  );

  useEffect(() => {
    // Also tick briefly after events arrive (for flow arrow expiry)
    if (!hasActiveNodes && phase !== 'executing') return;
    const id = setInterval(() => setNow(Date.now()), TICK_INTERVAL_MS);
    return () => clearInterval(id);
  }, [hasActiveNodes, phase]);

  // Update `now` when new events arrive so flows appear immediately
  useEffect(() => {
    setNow(Date.now());
  }, [events]);

  const activeFlows = useMemo(
    () => deriveActiveFlows(events, state, now),
    [events, state, now],
  );

  // Return a getter rather than a precomputed map — only nodes that are
  // actually rendered will call it, avoiding unnecessary computation.
  const getProgress = useMemo(() => {
    return (nodeId) => getNodeProgress(nodeId, nodeStates[nodeId], events, reviewPlan, phase, now);
  }, [nodeStates, events, reviewPlan, phase, now]);

  return { activeFlows, getProgress };
}
