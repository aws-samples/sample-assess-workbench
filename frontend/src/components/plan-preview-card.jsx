// --- Plan Preview Card ---
// Displays the AI-generated review plan summary above the flow visualization.
// Collapsed by default after review completion — click header to expand.

import { useState } from 'preact/hooks';

export function PlanPreviewCard({ plan }) {
  const [collapsed, setCollapsed] = useState(true);
  if (!plan) return null;
  const agentCount = plan.groups?.reduce((sum, g) => sum + g.agents.length, 0) || 0;
  const complexityColor = plan.complexity === 'high' ? '#e74c3c'
    : plan.complexity === 'medium' ? '#f39c12' : '#27ae60';
  const hasDetails = plan.rationale || plan.warnings?.length > 0;
  return (
    <div class="rv-plan-card">
      <div class="rv-plan-card-header">
        <span>📋</span>
        <span class="rv-plan-card-title">Review Plan</span>
        <span class="rv-plan-card-count">{agentCount} agents, {plan.groups?.length || 0} groups</span>
      </div>
      <div class="rv-plan-card-meta">
        <span>Type: <strong>{plan.document_type?.replace(/_/g, ' ')}</strong></span>
        <span>Complexity: <strong style={`color:${complexityColor}`}>{plan.complexity}</strong></span>
        {hasDetails && (
          <button class="rv-plan-toggle" onClick={() => setCollapsed(!collapsed)} type="button">
            {collapsed ? 'Show plan details ▾' : 'Hide plan details ▴'}
          </button>
        )}
      </div>
      {!collapsed && (
        <>
          {plan.rationale && (
            <p class="rv-plan-card-rationale">&ldquo;{plan.rationale}&rdquo;</p>
          )}
          {plan.warnings?.length > 0 && (
            <div class="rv-plan-card-warnings">
              {plan.warnings.map((w, i) => (
                <p key={i} class="rv-plan-card-warning">⚠️ {w.message}</p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
