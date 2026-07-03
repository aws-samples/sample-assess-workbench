// --- Review Metrics Summary (shown after review completion) ---

import { fmtTokens } from '../lib/format-utils.js';
import { useAgents } from '../agent-context.jsx';

export function ReviewMetricsSummary({ metrics }) {
  if (!metrics || !metrics.total_tokens) return null;
  const { agents } = useAgents();
  const byAgent = metrics.by_agent || {};
  const agentKeys = Object.keys(byAgent);
  const imgMetrics = metrics.image_analysis;
  const judgeByAgent = metrics.judge?.by_agent || {};
  return (
    <div class="rv-metrics-summary">
      <div class="rv-metrics-header">
        <span>📊</span>
        <span style="font-weight:600">Review Performance</span>
      </div>
      <div class="rv-metrics-totals">
        {metrics.planning_duration_ms > 0 && (
          <div class="rv-metric-card">
            <span class="rv-metric-value">{(metrics.planning_duration_ms / 1000).toFixed(1)}s</span>
            <span class="rv-metric-label">Planning</span>
          </div>
        )}
        <div class="rv-metric-card">
          <span class="rv-metric-value">{fmtTokens(metrics.total_tokens)}</span>
          <span class="rv-metric-label">Total Tokens</span>
        </div>
        <div class="rv-metric-card">
          <span class="rv-metric-value">{fmtTokens(metrics.input_tokens)}</span>
          <span class="rv-metric-label">Input</span>
        </div>
        <div class="rv-metric-card">
          <span class="rv-metric-value">{fmtTokens(metrics.output_tokens)}</span>
          <span class="rv-metric-label">Output</span>
        </div>
        {metrics.cache_read_tokens > 0 && (
          <div class="rv-metric-card">
            <span class="rv-metric-value">{fmtTokens(metrics.cache_read_tokens)}</span>
            <span class="rv-metric-label">Cache Hits</span>
          </div>
        )}
        <div class="rv-metric-card">
          <span class="rv-metric-value">{metrics.total_cycles || 0}</span>
          <span class="rv-metric-label">Cycles</span>
        </div>
        {imgMetrics && imgMetrics.total_tokens > 0 && (
          <div class="rv-metric-card">
            <span class="rv-metric-value">{imgMetrics.images_analyzed || 0}</span>
            <span class="rv-metric-label">Images Analyzed</span>
          </div>
        )}
      </div>
      {(agentKeys.length > 0 || (imgMetrics && imgMetrics.total_tokens > 0)) && (
        <div class="rv-metrics-agents">
          <table class="rv-metrics-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Tokens</th>
                <th>Cycles</th>
                <th>
                  <span class="header-with-tooltip">
                    Agent Duration <span class="tooltip-icon">ⓘ</span>
                    <span class="tooltip-text">Total time for the AgentCore invocation</span>
                  </span>
                </th>
                <th>
                  <span class="header-with-tooltip">
                    Model Time <span class="tooltip-icon">ⓘ</span>
                    <span class="tooltip-text">Time spent in model inference cycles</span>
                  </span>
                </th>
                <th>
                  <span class="header-with-tooltip">
                    Overhead <span class="tooltip-icon">ⓘ</span>
                    <span class="tooltip-text">AgentCore routing, network, and serialization overhead</span>
                  </span>
                </th>
                <th>
                  <span class="header-with-tooltip">
                    Coach <span class="tooltip-icon">ⓘ</span>
                    <span class="tooltip-text">Duration of each coach judge iteration</span>
                  </span>
                </th>
                <th>
                  <span class="header-with-tooltip">
                    Quality Judge <span class="tooltip-icon">ⓘ</span>
                    <span class="tooltip-text">Duration of the final quality evaluation</span>
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {imgMetrics && imgMetrics.total_tokens > 0 && (
                <tr>
                  <td>🖼️ Image Analysis</td>
                  <td>{fmtTokens(imgMetrics.total_tokens)}</td>
                  <td>{imgMetrics.images_analyzed || 0} img{imgMetrics.images_skipped > 0 ? ` (${imgMetrics.images_skipped} skip)` : ''}</td>
                  <td>{imgMetrics.duration_ms ? (imgMetrics.duration_ms / 1000).toFixed(1) + 's' : '—'}</td>
                  <td>—</td>
                  <td>—</td>
                  <td>—</td>
                  <td>—</td>
                </tr>
              )}
              {agentKeys.map(a => {
                const am = byAgent[a];
                const meta = agents[a] || {};
                const agentDuration = am.lambda_duration_s || 0;
                const modelTime = am.total_duration_s || 0;
                const overhead = agentDuration && modelTime
                  ? Math.max(0, agentDuration - modelTime)
                  : null;
                const coachDurations = am.coach_durations || [];
                const judgeDuration = judgeByAgent[a];
                return (
                  <tr key={a}>
                    <td>{meta.icon || ''} {meta.display_name || a}</td>
                    <td>{fmtTokens(am.total_tokens)}</td>
                    <td>{am.cycle_count || '—'}</td>
                    <td>{agentDuration ? agentDuration.toFixed(1) + 's' : '—'}</td>
                    <td>{modelTime ? modelTime.toFixed(1) + 's' : '—'}</td>
                    <td>{overhead != null ? overhead.toFixed(1) + 's' : '—'}</td>
                    <td>{coachDurations.length > 0 ? coachDurations.map(d => d.toFixed(1) + 's').join(', ') : '—'}</td>
                    <td>{judgeDuration != null ? judgeDuration.toFixed(1) + 's' : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
