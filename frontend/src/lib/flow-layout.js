// Graph layout and edge computation for the live review visualization.
// Pure functions — no component state, no side effects.

export const UTILITY_NODES = { s3: 'left', memory: 'right' };

export function computeLayout(pipeline, agents, hasImageAnalysis, hasQualityJudge, coachAgents) {
  const positions = {};
  const baseW = hasImageAnalysis ? 1200 : 1100;
  const stageGap = 160, topPad = 80, agentSpacing = 160;

  // Auto-widen canvas for large agent counts
  const maxAgentsInStage = pipeline.reduce((max, s) => Math.max(max, s.agents.length), 0);
  const coachPadding = coachAgents && coachAgents.size > 0 ? 140 : 0;
  const W = Math.max(baseW, maxAgentsInStage * agentSpacing + 200 + coachPadding);

  // Top row: S3, Document Processing, [Image Analysis], Orchestrator, Registry
  const topY = topPad;
  if (hasImageAnalysis) {
    const nodeSpacing = W / 6;
    positions.s3 = { x: nodeSpacing, y: topY };
    positions.document_processing = { x: nodeSpacing * 2, y: topY };
    positions.image_analysis = { x: nodeSpacing * 3, y: topY };
    positions.orchestrator = { x: nodeSpacing * 4, y: topY };
    positions.registry = { x: nodeSpacing * 5, y: topY };
    positions.memory = { x: nodeSpacing * 5, y: topY + 120 };
  } else {
    positions.document_processing = { x: W / 2 - 160, y: topY };
    positions.s3 = { x: W / 2 - 320, y: topY };
    positions.orchestrator = { x: W / 2 + 80, y: topY };
    positions.registry = { x: W / 2 + 280, y: topY };
    positions.memory = { x: W / 2 + 280, y: topY + 120 };
  }

  let currentY = topY + stageGap;
  // Reserve right column for Registry/Memory/Quality Judge (last ~180px of canvas)
  const agentAreaWidth = W - 200;
  const stageSeparators = []; // Y positions for horizontal separator lines
  // Separator between infra row and first agent stage (only when stages exist)
  if (pipeline.length > 0) {
    stageSeparators.push(topY + stageGap / 2);
  }
  pipeline.forEach((stage, idx) => {
    if (idx > 0) {
      // Midpoint between previous stage bottom and this stage top
      stageSeparators.push(currentY - stageGap / 2);
    }
    const count = stage.agents.length;
    const hasCoachInStage = stage.agents.some(a => coachAgents && coachAgents.has(a));
    // Spread agents across available area, accounting for coach offset
    const coachOffset = hasCoachInStage ? 120 : 0;
    const effectiveSpacing = Math.min(agentSpacing, (agentAreaWidth - coachOffset) / count);
    const totalWidth = count * effectiveSpacing;
    const startX = (agentAreaWidth - totalWidth) / 2 + effectiveSpacing / 2;
    stage.agents.forEach((agentId, i) => {
      positions[agentId] = { x: startX + i * effectiveSpacing, y: currentY };
      if (coachAgents && coachAgents.has(agentId)) {
        positions[`coach_${agentId}`] = { x: startX + i * effectiveSpacing + 120, y: currentY + 100 };
      }
    });
    currentY += stageGap + (hasCoachInStage ? 80 : 0);
  });

  if (hasQualityJudge) {
    positions.quality_judge = { x: positions.memory.x, y: positions.memory.y + 120 };
  }

  // Crop canvas to tight bounding box around actual node positions
  const marginX = 60;
  const marginY = 100; // extra vertical room for expanded nodes/badges
  const allX = Object.values(positions).map(p => p.x);
  const allY = Object.values(positions).map(p => p.y);
  const minX = Math.min(...allX);
  const maxX = Math.max(...allX);
  const minY = Math.min(...allY);
  const maxY = Math.max(...allY);

  // Shift all positions so the leftmost/topmost node sits at margin
  const shiftX = minX - marginX;
  const shiftY = minY - marginY;
  for (const key of Object.keys(positions)) {
    positions[key] = { x: positions[key].x - shiftX, y: positions[key].y - shiftY };
  }

  // Shift separators by the same Y offset
  const shiftedSeparators = stageSeparators.map(y => y - shiftY);
  // Agent area boundary (X limit for separator lines, before right column)
  // Find the midpoint between rightmost pipeline agent and leftmost utility node
  const rightColumnNodes = ['registry', 'memory', 'quality_judge'].filter(k => positions[k]);
  const pipelineAgentIds = pipeline.flatMap(s => s.agents);
  const coachIds = [...(coachAgents || [])].map(a => `coach_${a}`).filter(k => positions[k]);
  const allAgentX = [...pipelineAgentIds, ...coachIds].filter(k => positions[k]).map(k => positions[k].x);
  const rightColX = rightColumnNodes.map(k => positions[k].x);
  const maxAgentX = allAgentX.length > 0 ? Math.max(...allAgentX) : 0;
  const minRightColX = rightColX.length > 0 ? Math.min(...rightColX) : croppedWidth;
  const separatorMaxX = (maxAgentX + minRightColX) / 2;

  const croppedWidth = (maxX - minX) + marginX * 2;
  const croppedHeight = (maxY - minY) + marginY * 2;

  return { positions, width: croppedWidth, height: croppedHeight, separators: shiftedSeparators, separatorMaxX };
}

export function computeEdges(pipeline, hasImageAnalysis, hasQualityJudge, coachAgents) {
  const edges = [];
  edges.push({ from: 'document_processing', to: 's3' });
  if (hasImageAnalysis) {
    edges.push({ from: 'document_processing', to: 'image_analysis' });
    edges.push({ from: 'image_analysis', to: 'orchestrator' });
  } else {
    edges.push({ from: 'document_processing', to: 'orchestrator' });
  }
  if (hasQualityJudge) {
    edges.push({ from: 'orchestrator', to: 'quality_judge' });
  }
  Object.keys(UTILITY_NODES).forEach(id => {
    if (id !== 's3') edges.push({ from: 'orchestrator', to: id });
  });
  edges.push({ from: 'registry', to: 'orchestrator' });
  pipeline.forEach((stage) => {
    stage.agents.forEach(agentId => {
      edges.push({ from: 'orchestrator', to: agentId });
      if (coachAgents && coachAgents.has(agentId)) {
        edges.push({ from: agentId, to: `coach_${agentId}` });
      }
    });
  });
  return edges;
}
