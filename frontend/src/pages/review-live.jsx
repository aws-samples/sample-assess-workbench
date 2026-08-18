// =============================================================================
// Live Review Page — pure rendering layer.
// State machine: ../lib/review-state-machine.js
// Side effects:  ../hooks/useReviewOrchestrator.js
// =============================================================================

import { route } from 'preact-router';
import { FlowLine, AgentNode, DocProcessingNode, ImageAnalysisNode } from '../components/flow-graph.jsx';
import { ProgressRing } from '../components/progress-ring.jsx';
import { PlanCustomizePanel } from '../components/plan-customize-panel.jsx';
import { PlanPreviewCard } from '../components/plan-preview-card.jsx';
import { ReviewMetricsSummary } from '../components/review-metrics.jsx';
import { SplitPanel } from '../components/split-panel.jsx';
import { formatEventName, formatDetail, eventColor } from '../lib/event-formatters.js';
import { UTILITY_NODES, computeLayout, computeEdges } from '../lib/flow-layout.js';
import { useReviewOrchestrator } from '../hooks/useReviewOrchestrator.js';
import { useFlowVisuals } from '../hooks/useFlowVisuals.js';
import { useContainerScale } from '../hooks/useContainerScale.js';
import { useI18n } from '../i18n-context.jsx';

export function AgentDemoPage({ projectId, reviewId }) {
  const {
    state, isLive, flowAgents, projectName,
    approving, customizing, setCustomizing, demoRunning,
    originalPlanRef,
    handleApprove, handleReject, handleAbort, handleCustomizeSave, handleCustomizeChange,
    runDemo, resetDemo,
  } = useReviewOrchestrator(projectId, reviewId);

  const { phase, nodeStates, statusLabel, events,
          pipeline, reviewPlan, agentMetrics, reviewMetrics, docFileEvents,
          imageEvents, qualityScores, coachState, toolCalls } = state;

  const { activeFlows, getProgress } = useFlowVisuals(state);
  const { t } = useI18n();

  // --- Derived layout ---
  const hasImageAnalysis = !!nodeStates.image_analysis;
  const hasQualityJudge = phase !== 'idle';
  const coachAgents = new Set();
  if (reviewPlan?.groups) {
    reviewPlan.groups.forEach(g => g.agents.forEach(a => {
      if (a.judge?.enabled) coachAgents.add(a.agent_type);
    }));
  }
  const { positions, width, height, separators, separatorMaxX } = computeLayout(pipeline, flowAgents, hasImageAnalysis, hasQualityJudge, coachAgents);
  const edges = computeEdges(pipeline, hasImageAnalysis, hasQualityJudge, coachAgents);
  const { containerRef, scale } = useContainerScale(width);
  const isPreview = phase === 'preview';
  const planAgentMap = {};
  if (reviewPlan?.groups) {
    reviewPlan.groups.forEach(g => g.agents.forEach(a => { planAgentMap[a.agent_type] = a; }));
  }

  return (
    <section class="page-section page-section--wide">
      <h2>{isLive ? t('demo.liveReview') : t('demo.title')}</h2>
      <p class="subtitle" style="margin-bottom:1rem">
        {isLive
          ? phase === 'loading' ? t('demo.loadingSubtitle')
            : phase === 'preview' ? t('demo.previewSubtitle')
            : phase === 'executing' ? t('demo.executingSubtitle', { name: projectName })
            : phase === 'complete' ? t('demo.completeSubtitle')
            : phase === 'error' ? ''
            : t('demo.watchingSubtitle', { name: projectName })
          : t('demo.subtitle')}
      </p>

      {reviewPlan && (phase === 'preview' || phase === 'executing' || phase === 'complete') && (
        <PlanPreviewCard plan={reviewPlan} />
      )}

      <div class="rv-controls">
        {!isLive && !demoRunning && (
          <>
            <button class="btn btn-primary" onClick={runDemo}>{t('demo.runDemo')}</button>
            <button class="btn btn-secondary" onClick={resetDemo}>{t('demo.reset')}</button>
          </>
        )}
        {(isLive || demoRunning) && isPreview && reviewPlan?.groups && (
          <>
            <button class="btn btn-primary" onClick={() => handleApprove()} disabled={approving}>
              {approving ? t('demo.approving') : t('demo.startReview')}
            </button>
            <button class="btn btn-secondary" onClick={() => setCustomizing(!customizing)}>
              {customizing ? t('demo.hideEditor') : t('demo.customize')}
            </button>
            <button class="btn btn-secondary" onClick={handleReject}>{t('demo.reject')}</button>
          </>
        )}
        <span class={`rv-status ${phase === 'complete' && !statusLabel.startsWith('Failed') ? 'rv-status--done' : ''} ${statusLabel.startsWith('Failed') ? 'rv-status--failed' : ''}`}>{statusLabel}</span>
        {isLive && phase === 'executing' && (
          <button class="btn btn-danger btn-small" onClick={handleAbort} style="margin-left:auto">
            {t('demo.abort')}
          </button>
        )}
        {isLive && phase === 'complete' && (
          <button class="btn btn-primary btn-small" onClick={() => route(`/projects/${projectId}`)}>
            {t('demo.viewResults')}
          </button>
        )}
      </div>

      {(isLive || demoRunning) && isPreview && customizing && reviewPlan && (
        <PlanCustomizePanel
          plan={reviewPlan}
          originalPlan={originalPlanRef.current}
          onSave={handleCustomizeSave}
          onCancel={() => setCustomizing(false)}
          onChange={handleCustomizeChange}
        />
      )}

      {phase === 'error' && (
        <div class="rv-error-banner" role="alert">
          <p class="rv-error-message">{statusLabel}</p>
          <button class="btn btn-primary" onClick={() => window.location.reload()}>
            Retry
          </button>
        </div>
      )}

      {(phase !== 'idle') && (
        <SplitPanel defaultSplit={65} minLeft={40} maxLeft={80} style={{ height: `${Math.round(height * scale) + 32}px` }}>
          <div
            class="rv-graph-container"
            ref={containerRef}
            style={{ width: '100%', height: `${Math.round(height * scale)}px` }}
          >
            <div
              class="rv-canvas"
              style={{
                width: `${width}px`, height: `${height}px`,
                transform: `scale(${scale})`, transformOrigin: 'top left',
              }}
              role="img"
              aria-label={
                phase === 'idle' ? t('demo.ariaIdle')
                : phase === 'loading' ? t('demo.ariaLoading')
                : phase === 'preview' ? t('demo.ariaPreview', { count: pipeline.reduce((s, st) => s + st.agents.length, 0) })
                : phase === 'executing' ? t('demo.ariaExecuting', { count: Object.values(nodeStates).filter(s => s === 'done').length })
                : phase === 'complete' ? t('demo.ariaComplete') : phase === 'error' ? statusLabel : t('demo.ariaIdle')
              }
        >
          <svg class="rv-svg" width={width} height={height}>
            {edges.map(({ from, to }) => {
              const pFrom = positions[from];
              const pTo = positions[to];
              if (!pFrom || !pTo) return null;
              const isActive = activeFlows.some(f => (f.from === from && f.to === to) || (f.from === to && f.to === from));
              const isReturning = activeFlows.some(f => f.from === to && f.to === from);
              const isCoachEdge = from.startsWith('coach_') || to.startsWith('coach_');
              const agentForCoach = isCoachEdge ? (from.replace('coach_', '') || to.replace('coach_', '')) : null;
              const color = isCoachEdge
                ? (flowAgents[agentForCoach]?.color)
                : (from === 'orchestrator' || to === 'orchestrator')
                  ? (flowAgents[from === 'orchestrator' ? to : from]?.color)
                  : (flowAgents[to]?.color);
              const actualFrom = isReturning ? pTo : pFrom;
              const actualTo = isReturning ? pFrom : pTo;
              const isBidirectional = (from === 'document_processing' && to === 's3') || (from === 's3' && to === 'document_processing');
              return <FlowLine key={`${from}-${to}`} from={actualFrom} to={actualTo} active={isActive} color={color} bidirectional={isActive && isBidirectional} />;
            })}
            {/* Dynamic flow lines for active flows not covered by static edges (e.g. agent → memory) */}
            {activeFlows.filter(f => !edges.some(e =>
              (e.from === f.from && e.to === f.to) || (e.from === f.to && e.to === f.from)
            )).map(f => {
              const pFrom = positions[f.from];
              const pTo = positions[f.to];
              if (!pFrom || !pTo) return null;
              const color = flowAgents[f.from]?.color || flowAgents[f.to]?.color || '#888';
              return <FlowLine key={`dyn-${f.from}-${f.to}`} from={pFrom} to={pTo} active color={color} />;
            })}
            {separators.map((y, i) => (
              <line key={`sep-${i}`} x1={0} y1={y} x2={separatorMaxX} y2={y} stroke="var(--border-color)" stroke-width="2" opacity="0.8" stroke-dasharray="8 4" />
            ))}
          </svg>

          <DocProcessingNode
            status={nodeStates.document_processing || ''}
            progress={getProgress('document_processing')}
            style={{ left: `${positions.document_processing.x}px`, top: `${positions.document_processing.y}px` }}
            fileEvents={docFileEvents}
          />
          {hasImageAnalysis && positions.image_analysis && (
            <ImageAnalysisNode
              status={nodeStates.image_analysis || ''}
              progress={getProgress('image_analysis')}
              style={{ left: `${positions.image_analysis.x}px`, top: `${positions.image_analysis.y}px` }}
              imageEvents={imageEvents}
            />
          )}
          {hasQualityJudge && positions.quality_judge && (
            <div
              class={`rv-node ${nodeStates.quality_judge === 'active' ? 'rv-node--active' : nodeStates.quality_judge === 'done' ? 'rv-node--done' : nodeStates.quality_judge === 'error' ? 'rv-node--error' : ''}`}
              style={{ left: `${positions.quality_judge.x}px`, top: `${positions.quality_judge.y}px`, '--node-color': '#3498db' }}
            >
              {nodeStates.quality_judge === 'done' && <span class="rv-node-check">✓</span>}
              {nodeStates.quality_judge === 'error' && <span class="rv-node-check" style="color:#e74c3c">✗</span>}
              <span class="rv-node-icon">🔍</span>
              <span class="rv-node-label">{t('demo.qualityJudge')}</span>
              {nodeStates.quality_judge === 'active' && getProgress('quality_judge') > 0 && (
                <ProgressRing progress={getProgress('quality_judge')} color="#3498db" size={32} />
              )}
              {nodeStates.quality_judge === 'done' && Object.keys(qualityScores).length > 0 && (
                <div class="rv-node-metrics" style="flex-direction:column;gap:1px">
                  {Object.entries(qualityScores).map(([agent, score]) => (
                    <span key={agent} style={{ fontSize: '0.6rem', opacity: 0.85 }}>{agent}: {score.toFixed(2)}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          <AgentNode
            agent="orchestrator"
            status={nodeStates.orchestrator || ''}
            progress={getProgress('orchestrator')}
            style={{ left: `${positions.orchestrator.x}px`, top: `${positions.orchestrator.y}px` }}
            labelOverride={phase === 'loading' ? t('demo.planner') : phase === 'executing' ? t('demo.orchestrating') : t('demo.orchestrator')}
            agentsMap={flowAgents}
          />
          {positions.registry && (
            <AgentNode agent="registry" status={nodeStates.registry || ''} style={{ left: `${positions.registry.x}px`, top: `${positions.registry.y}px` }} agentsMap={flowAgents} />
          )}
          {Object.keys(UTILITY_NODES).map(agentId => {
            const pos = positions[agentId];
            if (!pos) return null;
            return (
              <AgentNode
                key={agentId} agent={agentId}
                status={agentId === 's3' && isPreview ? 'done' : nodeStates[agentId] || ''}
                progress={getProgress(agentId)}
                style={{ left: `${pos.x}px`, top: `${pos.y}px` }}
                agentsMap={flowAgents}
              />
            );
          })}
          {pipeline.map(stage =>
            stage.agents.map(agentId => {
              const pos = positions[agentId];
              if (!pos) return null;
              const planAgent = planAgentMap[agentId];
              const cs = coachState[agentId];
              const agentLabel = flowAgents[agentId]?.label || agentId;
              const tipParts = [agentLabel];
              if (planAgent?.depth) tipParts.push(t('demo.depth', { value: planAgent.depth }));
              return (
                <AgentNode
                  key={agentId} agent={agentId} agentsMap={flowAgents}
                  status={nodeStates[agentId] || ''}
                  progress={getProgress(agentId)}
                  style={{ left: `${pos.x}px`, top: `${pos.y}px` }}
                  expanded={isPreview} depth={planAgent?.depth}
                  metrics={agentMetrics[agentId]}
                  iterationBadge={cs ? { iteration: cs.iteration, status: cs.status } : null}
                  toolCallsBadge={toolCalls[agentId] ? {
                    total: toolCalls[agentId].total,
                    tooltip: Object.entries(toolCalls[agentId].tools).map(([t, n]) => `${t}: ${n}`).join(', '),
                  } : null}
                  tooltip={tipParts.join('\n')}
                />
              );
            })
          )}
          {[...coachAgents].map(agentId => {
            const coachId = `coach_${agentId}`;
            const pos = positions[coachId];
            if (!pos) return null;
            const cs = coachState[agentId];
            const status = nodeStates[coachId] || '';
            const planAgent = planAgentMap[agentId];
            const judge = planAgent?.judge;
            const coachTipParts = [t('demo.coachFor', { agent: flowAgents[agentId]?.label || agentId })];
            if (judge) {
              coachTipParts.push(t('demo.threshold', { value: judge.quality_threshold ?? 'default' }));
              coachTipParts.push(t('demo.maxIterations', { value: judge.max_iterations ?? 'default' }));
            }
            return (
              <div
                key={coachId}
                title={coachTipParts.join('\n')}
                class={`rv-node rv-node--coach ${status === 'active' ? 'rv-node--active' : status === 'done' ? 'rv-node--done' : ''}`}
                style={{ left: `${pos.x}px`, top: `${pos.y}px`, '--node-color': flowAgents[agentId]?.color }}
              >
                {cs?.status === 'pass' && <span class="rv-node-check">✓</span>}
                {cs?.status === 'fail' && <span class="rv-node-check" style="background:var(--warning-color);color:#333">↩</span>}
                <span class="rv-node-icon">📋</span>
                <span class="rv-node-label">{t('demo.coach')}</span>
                {cs && cs.score != null && (
                  <span class={`rv-coach-score ${cs.status === 'pass' ? 'rv-coach-score--pass' : 'rv-coach-score--fail'}`}>
                    {cs.score.toFixed(2)}
                  </span>
                )}
              </div>
            );
          })}
          {pipeline.map((stage, idx) => {
            const firstPos = positions[stage.agents[0]];
            if (!firstPos) return null;
            const icon = stage.type === 'parallel' ? '⫘' : '→';
            const agentNames = stage.agents.map(a => flowAgents[a]?.label || a).join(', ');
            const tooltip = t('demo.stageTooltip', { label: stage.label, count: stage.agents.length, type: stage.type === 'parallel' ? t('demo.parallel') : t('demo.sequential'), agents: agentNames });
            return (
              <span key={stage.id} class="rv-stage-label" title={tooltip} style={{ top: `${firstPos.y - 30}px` }}>
                {icon} {t('demo.layer', { index: idx + 1 })} <span class="rv-stage-info">ⓘ</span>
              </span>
            );
          })}
        </div>
          </div>
          <div class="rv-timeline-panel custom-scroll">
            <h3 class="rv-timeline-title">{t('demo.eventLog')}</h3>
            {events.length > 0 ? (
              <div class="rv-timeline-list">
                {[...events].reverse().map((e, i) => (
                  <div key={i} class="rv-timeline-item">
                    <span class="rv-timeline-dot" style={{ background: eventColor(e.event, e.detail, flowAgents) }} />
                    <span class="rv-timeline-time">{new Date(e.ts).toLocaleTimeString()}</span>
                    <span class="rv-timeline-event">{formatEventName(e.event)}</span>
                    <span class="rv-timeline-detail">{formatDetail(e.event, e.detail, flowAgents)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p class="empty-panel-text">{t('demo.eventsEmpty')}</p>
            )}
          </div>
        </SplitPanel>
      )}

      {phase === 'complete' && reviewMetrics && (
        <ReviewMetricsSummary metrics={reviewMetrics} agentMetrics={agentMetrics} />
      )}
    </section>
  );
}
