// =============================================================================
// Progress model — strategy functions for computing node progress.
//
// Each function is pure: (inputs) → number between 0 and 1.
// No Date.now() calls — the caller passes `now` so these are testable.
// =============================================================================

/**
 * Exponential-curve progress for agent nodes.
 * Approaches but never reaches 1.0 until explicitly completed.
 *
 * @param {number} startedAt - Timestamp (ms) when the agent started
 * @param {number} now - Current timestamp (ms)
 * @param {number} [estimatedDurationMs=30000] - Expected duration
 * @returns {number} Progress between 0 and 0.92
 */
export function agentProgress(startedAt, now, estimatedDurationMs = 30000) {
  if (!startedAt || now <= startedAt) return 0;
  const elapsed = now - startedAt;
  return Math.min(0.92, 1 - Math.exp(-2.5 * (elapsed / estimatedDurationMs)));
}

/**
 * Milestone-based progress for the orchestrator node.
 * Jumps on completions, creeps between them.
 *
 * @param {number} completedWeight - Sum of completed step weights
 * @param {number} totalWeight - Sum of all step weights
 * @param {number|null} lastEventAt - Timestamp (ms) of last progress event
 * @param {number} now - Current timestamp (ms)
 * @returns {number} Progress between 0 and 1
 */
export function orchestratorProgress(completedWeight, totalWeight, lastEventAt, now) {
  if (totalWeight === 0) return 0;
  const milestone = completedWeight / totalWeight;
  if (milestone >= 1) return 1;
  if (!lastEventAt) return milestone;
  const elapsed = (now - lastEventAt) / 1000;
  const nextStepWeight = 10;
  const nextMilestone = Math.min((completedWeight + nextStepWeight) / totalWeight, 1);
  const creepRange = nextMilestone - milestone;
  const creep = creepRange * (1 - Math.exp(-elapsed / 8));
  return Math.min(milestone + creep, nextMilestone - 0.01);
}

// Default estimated durations per node type (ms).
// These are rough heuristics — the post-refactor improvement in the plan
// will replace them with real historical data from the backend.
export const DURATION_ESTIMATES = {
  document_processing: 15000,
  image_analysis: 20000,
  orchestrator: 40000,
  s3: 3000,
  architecture: 45000,
  security: 45000,
  risk: 45000,
  memory: 5000,
  quality_judge: 8000,
};
