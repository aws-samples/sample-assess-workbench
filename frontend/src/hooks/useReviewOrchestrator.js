// =============================================================================
// useReviewOrchestrator — custom hook for all review flow side effects.
// WebSocket subscription, state recovery, polling, approve/reject, demo runner.
// =============================================================================

import { useState, useEffect, useRef, useCallback, useReducer } from 'preact/hooks';
import { route } from 'preact-router';
import { approveReviewPlan, rejectReviewPlan, abortReview, getReviewPlan, getProject } from '../api.js';
import { useWs } from '../ws-context.jsx';
import { useFlowAgents } from '../components/flow-graph.jsx';
import { DEMO_STEPS } from '../lib/demo-steps.js';
import { reducer, INITIAL_STATE } from '../lib/review-state-machine.js';
import { useEventStream } from './useEventStream.js';

export function useReviewOrchestrator(projectId, initialReviewId) {
  const ws = useWs();
  const isLive = !!projectId && !!ws;
  const flowAgents = useFlowAgents();

  const [state, dispatch] = useReducer(reducer, { ...INITIAL_STATE, phase: isLive ? 'loading' : 'idle' });
  const { phase, reviewPlan } = state;

  // Non-reducer state
  const [projectName, setProjectName] = useState('');
  const [approving, setApproving] = useState(false);
  const [customizing, setCustomizing] = useState(false);
  const [demoRunning, setDemoRunning] = useState(false);
  const originalPlanRef = useRef(null);
  const reviewIdRef = useRef(initialReviewId || null);
  const demoTimer = useRef(null);
  const demoIndex = useRef(0);
  const demoPaused = useRef(false);
  const demoResumeRef = useRef(null);

  // --- Dispatch an event + schedule side effects ---
  const handleEvent = useCallback((event, detail, ts) => {
    if (event === 'plan_created') {
      const plan = detail.plan || detail;
      if (!originalPlanRef.current) originalPlanRef.current = JSON.parse(JSON.stringify(plan));
      reviewIdRef.current = detail.review_id || null;
    }
    dispatch({ type: 'EVENT', event, detail, agentsMap: flowAgents, ts });
  }, [flowAgents]);

  // --- Event stream: single source of truth for review events ---
  const onEvents = useCallback((events, resolvedReviewId) => {
    if (resolvedReviewId) reviewIdRef.current = resolvedReviewId;
    for (const ev of events) {
      handleEvent(ev.event, ev.detail || {}, ev.ts);
    }
  }, [handleEvent]);

  const onStreamError = useCallback((err) => {
    dispatch({ type: 'SET_ERROR', label: err.message || 'Failed to load review events' });
  }, []);

  useEventStream({
    projectId: isLive ? projectId : null,
    initialReviewId: initialReviewId || null,
    phase,
    onEvents,
    onError: onStreamError,
  });

  // --- Fetch project name ---
  useEffect(() => {
    if (!projectId) return;
    getProject(projectId).then(p => setProjectName(p.name || '')).catch(() => setProjectName(''));
  }, [projectId]);

  // --- Initial phase detection ---
  // On mount, check project/plan status to handle the pending_approval case
  // where events alone can't tell us the plan needs approval (plan_created
  // fires, but approval status lives on the plan record).
  const loadInitialPhase = useCallback(async () => {
    if (!projectId) return;
    try {
      const project = await getProject(projectId);
      if (project.status === 'in_progress') {
        const planData = await getReviewPlan(projectId, 'latest').catch(() => null);
        if (planData?.status === 'pending_approval') {
          if (!originalPlanRef.current) originalPlanRef.current = JSON.parse(JSON.stringify(planData.plan));
          reviewIdRef.current = planData.SK?.replace('PLAN#', '') || null;
          dispatch({ type: 'LOAD_PREVIEW', plan: planData.plan });
        }
      }
    } catch (err) {
      dispatch({ type: 'SET_ERROR', label: err.message || 'Failed to load review state' });
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId && isLive) loadInitialPhase();
  }, [projectId, isLive, loadInitialPhase]);

  // --- Demo ---
  const runDemo = useCallback(() => {
    dispatch({ type: 'RESET', phase: 'loading' });
    dispatch({ type: 'SET_STATUS', label: 'Starting demo…' });
    setDemoRunning(true);
    demoIndex.current = 0;
    demoPaused.current = false;
    function next() {
      if (demoIndex.current >= DEMO_STEPS.length) { setDemoRunning(false); return; }
      const step = DEMO_STEPS[demoIndex.current];
      demoTimer.current = setTimeout(() => {
        handleEvent(step.event, step.detail);
        demoIndex.current++;
        // Pause after plan_created when approval is required
        if (step.event === 'plan_created' && step.detail?.requires_approval !== false) {
          demoPaused.current = true;
          demoResumeRef.current = next;
          return;
        }
        next();
      }, step.delay);
    }
    next();
  }, [handleEvent]);

  const resumeDemo = useCallback(() => {
    if (demoPaused.current && demoResumeRef.current) {
      demoPaused.current = false;
      const next = demoResumeRef.current;
      demoResumeRef.current = null;
      next();
    }
  }, []);

  const resetDemo = useCallback(() => {
    clearTimeout(demoTimer.current);
    demoPaused.current = false;
    demoResumeRef.current = null;
    setDemoRunning(false);
    dispatch({ type: 'RESET' });
  }, []);

  // --- Approve ---
  const handleApprove = useCallback(async () => {
    // Demo mode: dispatch plan_approved locally and resume the demo runner
    if (!isLive && demoRunning) {
      dispatch({ type: 'EVENT', event: 'plan_approved', detail: { auto: false } });
      setCustomizing(false);
      resumeDemo();
      return;
    }
    const rid = reviewIdRef.current;
    console.log('[approve] rid:', rid, 'projectId:', projectId, 'phase:', phase);
    if (!projectId || !rid) {
      dispatch({ type: 'SET_STATUS', label: 'Cannot approve — review ID not available yet' });
      return;
    }
    setApproving(true);
    try {
      await approveReviewPlan(projectId, rid, reviewPlan || undefined);
      setCustomizing(false);
      console.log('[approve] dispatching plan_approved');
      dispatch({ type: 'EVENT', event: 'plan_approved', detail: { auto: false } });
    } catch (e) {
      console.error('[approve] failed:', e);
      dispatch({ type: 'SET_STATUS', label: `Approve failed: ${e.message}` });
    } finally {
      setApproving(false);
    }
  }, [isLive, demoRunning, resumeDemo, projectId, reviewPlan]);

  const handleCustomizeSave = useCallback((editedPlan) => {
    dispatch({ type: 'SET_PLAN', plan: editedPlan });
    setCustomizing(false);
  }, []);
  const handleCustomizeChange = useCallback((editedPlan) => dispatch({ type: 'SET_PLAN', plan: editedPlan }), []);

  // --- Reject ---
  const handleReject = useCallback(async () => {
    // Demo mode: just reset
    if (!isLive && demoRunning) {
      resetDemo();
      return;
    }
    const rid = reviewIdRef.current;
    if (!projectId || !rid) return;
    try {
      await rejectReviewPlan(projectId, rid);
      dispatch({ type: 'SET_PHASE', phase: 'idle' });
      dispatch({ type: 'SET_STATUS', label: 'Review plan rejected' });
      setTimeout(() => route(`/projects/${projectId}`), 1500);
    } catch (e) {
      dispatch({ type: 'SET_STATUS', label: `Reject failed: ${e.message}` });
    }
  }, [isLive, demoRunning, resetDemo, projectId]);

  const handleAbort = useCallback(async () => {
    const rid = reviewIdRef.current;
    if (!projectId || !rid) return;
    try {
      await abortReview(projectId, rid);
      dispatch({ type: 'EVENT', event: 'review_aborted', detail: { reason: 'user_abort', failed_agents: [] }, agentsMap: flowAgents });
    } catch (e) {
      dispatch({ type: 'SET_STATUS', label: `Abort failed: ${e.message}` });
    }
  }, [projectId, flowAgents]);

  return {
    state,
    isLive,
    flowAgents,
    projectName,
    approving,
    customizing,
    setCustomizing,
    demoRunning,
    originalPlanRef,
    handleApprove,
    handleReject,
    handleAbort,
    handleCustomizeSave,
    handleCustomizeChange,
    runDemo,
    resetDemo,
  };
}
