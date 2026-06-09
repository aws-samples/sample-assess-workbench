import { useState, useEffect, useRef, useCallback } from 'preact/hooks';
import { useI18n } from '../i18n-context.jsx';
import { useAgents } from '../agent-context.jsx';
import { getAnalyticsSummary, getAnalyticsTrends, getAnalyticsCoverage, listProjects } from '../api.js';

export function AnalyticsPage() {
  const { t } = useI18n();
  const { agents } = useAgents();
  const [tab, setTab] = useState('quality');
  const [summary, setSummary] = useState(null);
  const [trends, setTrends] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    Promise.all([getAnalyticsSummary(), getAnalyticsTrends()])
      .then(([s, tr]) => {
        if (cancelled) return;
        setSummary(s);
        setTrends(tr);
      })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <div class="page-section"><p>{t('analytics.loading')}</p></div>;
  if (error) return <div class="page-section status-message error">{error}</div>;
  if (!summary || summary.review_count === 0) {
    return <div class="page-section"><p class="empty-state">{t('analytics.noData')}</p></div>;
  }

  const tabs = [
    { id: 'quality', label: t('analytics.qualityOverview') },
    { id: 'history', label: t('analytics.reviewHistory') },
    { id: 'feedback', label: t('analytics.feedbackSummary') },
    { id: 'coverage', label: t('analytics.coverageMatrix') },
  ];

  return (
    <div>
      <div class="page-section">
        <div class="page-header">
          <h2>{t('analytics.title')}</h2>
          <span class="badge secondary">{t('analytics.reviews', { count: summary.review_count })}</span>
        </div>
        <div class="tabs">
          {tabs.map((tb) => (
            <button key={tb.id} class={`tab-btn ${tab === tb.id ? 'active' : ''}`} onClick={() => setTab(tb.id)}>
              {tb.label}
            </button>
          ))}
        </div>
      </div>
      {tab === 'quality' && <QualityOverview summary={summary} agents={agents} />}
      {tab === 'history' && <ReviewHistory trends={trends} agents={agents} />}
      {tab === 'feedback' && <FeedbackSummary summary={summary} agents={agents} />}
      {tab === 'coverage' && <CoverageView />}
    </div>
  );
}

/* ── Quality Overview: Radar charts per agent ── */
function QualityOverview({ summary, agents }) {
  const agentTypes = Object.keys(summary.agent_scores);
  if (agentTypes.length === 0) return <div class="page-section"><p class="empty-state">No quality scores available.</p></div>;

  return (
    <div class="page-section">
      <div class="analytics-grid">
        {agentTypes.map((at) => {
          const scores = summary.agent_scores[at];
          const meta = agents[at] || {};
          return (
            <div key={at} class="analytics-card">
              <h3>{meta.icon || '📋'} {meta.display_name || at}</h3>
              <RadarChart scores={scores} color={meta.color || '#00a8e8'} />
              <div class="analytics-card-stats">
                <span>Overall: {scores.overall?.toFixed(2)}</span>
                <span class="text-secondary">{scores.review_count} reviews</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RadarChart({ scores, color }) {
  const canvasRef = useRef(null);
  const criteria = ['completeness', 'specificity', 'actionability'];
  const labels = criteria;
  const values = criteria.map((c) => scores[c] || 0);
  const scoresKey = JSON.stringify(values);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2 + 5, r = Math.min(cx, cy) - 45;

    ctx.clearRect(0, 0, w, h);

    const n = criteria.length;
    const angleStep = (2 * Math.PI) / n;
    const startAngle = -Math.PI / 2;

    // Draw grid rings
    for (let ring = 0.25; ring <= 1; ring += 0.25) {
      ctx.beginPath();
      for (let i = 0; i <= n; i++) {
        const angle = startAngle + i * angleStep;
        const x = cx + r * ring * Math.cos(angle);
        const y = cy + r * ring * Math.sin(angle);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = 'rgba(255,255,255,0.1)';
      ctx.stroke();
    }

    // Draw axes
    for (let i = 0; i < n; i++) {
      const angle = startAngle + i * angleStep;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
      ctx.strokeStyle = 'rgba(255,255,255,0.15)';
      ctx.stroke();
    }

    // Draw data polygon
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const idx = i % n;
      const angle = startAngle + idx * angleStep;
      const val = values[idx];
      const x = cx + r * val * Math.cos(angle);
      const y = cy + r * val * Math.sin(angle);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.fillStyle = color + '33';
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Draw data points
    for (let i = 0; i < n; i++) {
      const angle = startAngle + i * angleStep;
      const val = values[i];
      const x = cx + r * val * Math.cos(angle);
      const y = cy + r * val * Math.sin(angle);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    }

    // Draw labels
    ctx.fillStyle = '#b0b0b0';
    ctx.font = '11px -apple-system, sans-serif';
    for (let i = 0; i < n; i++) {
      const angle = startAngle + i * angleStep;
      const lx = cx + (r + 32) * Math.cos(angle);
      const ly = cy + (r + 32) * Math.sin(angle);
      // Align text based on position
      if (Math.abs(Math.cos(angle)) < 0.1) {
        ctx.textAlign = 'center';
      } else if (Math.cos(angle) > 0) {
        ctx.textAlign = 'left';
      } else {
        ctx.textAlign = 'right';
      }
      ctx.textBaseline = Math.sin(angle) < -0.5 ? 'bottom' : Math.sin(angle) > 0.5 ? 'top' : 'middle';
      ctx.fillText(labels[i], lx, ly);
    }
  }, [scoresKey, color]);

  return <canvas ref={canvasRef} width={320} height={280} class="radar-canvas" />;
}

/* ── Review History: Time series line chart ── */
function ReviewHistory({ trends, agents }) {
  const canvasRef = useRef(null);
  const trendsKey = JSON.stringify(trends?.data_points?.map(d => [d.agent_type, d.date, d.scores?.overall]) || []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !trends?.data_points?.length) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const pad = { top: 20, right: 20, bottom: 40, left: 50 };
    const plotW = w - pad.left - pad.right;
    const plotH = h - pad.top - pad.bottom;

    ctx.clearRect(0, 0, w, h);

    // Group by agent
    const byAgent = {};
    trends.data_points.forEach((dp) => {
      if (!byAgent[dp.agent_type]) byAgent[dp.agent_type] = [];
      byAgent[dp.agent_type].push(dp);
    });

    const allDates = trends.data_points.map((d) => new Date(d.date).getTime());
    const minDate = Math.min(...allDates);
    const maxDate = Math.max(...allDates);
    const dateRange = maxDate - minDate || 1;

    // Y axis (0 to 1)
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.fillStyle = '#b0b0b0';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = 'right';
    for (let v = 0; v <= 1; v += 0.25) {
      const y = pad.top + plotH * (1 - v);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
      ctx.fillText(v.toFixed(2), pad.left - 5, y + 3);
    }

    // Draw lines per agent
    Object.entries(byAgent).forEach(([at, points]) => {
      const meta = agents[at] || {};
      const color = meta.color || '#00a8e8';
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      points.forEach((dp, i) => {
        const x = pad.left + plotW * ((new Date(dp.date).getTime() - minDate) / dateRange);
        const y = pad.top + plotH * (1 - (dp.scores.overall || 0));
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Dots
      points.forEach((dp) => {
        const x = pad.left + plotW * ((new Date(dp.date).getTime() - minDate) / dateRange);
        const y = pad.top + plotH * (1 - (dp.scores.overall || 0));
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
      });
    });

    // Legend
    let lx = pad.left;
    ctx.font = '11px -apple-system, sans-serif';
    Object.entries(byAgent).forEach(([at]) => {
      const meta = agents[at] || {};
      ctx.fillStyle = meta.color || '#00a8e8';
      ctx.fillRect(lx, h - 15, 12, 12);
      ctx.fillStyle = '#b0b0b0';
      ctx.textAlign = 'left';
      ctx.fillText(meta.display_name || at, lx + 16, h - 5);
      lx += ctx.measureText(meta.display_name || at).width + 30;
    });
  }, [trendsKey, agents]);

  if (!trends?.data_points?.length) {
    return <div class="page-section"><p class="empty-state">No trend data available.</p></div>;
  }

  return (
    <div class="page-section">
      <canvas ref={canvasRef} width={800} height={300} class="chart-canvas" />
    </div>
  );
}

/* ── Feedback Summary: Per-agent bar chart ── */
function FeedbackSummary({ summary, agents }) {
  const { feedback_summary, total_feedback } = summary;
  const agentTypes = Object.keys(feedback_summary);

  if (agentTypes.length === 0) {
    return <div class="page-section"><p class="empty-state">No feedback data yet.</p></div>;
  }

  const totalRated = total_feedback.up + total_feedback.down;
  const totalFindings = agentTypes.reduce((sum, at) => sum + (feedback_summary[at].total_findings || 0), 0);

  return (
    <div class="page-section">
      <div class="feedback-overview">
        <span>Rated: {totalRated} of {totalFindings} findings</span>
        {totalRated > 0 && (
          <span class="text-secondary">
            ({Math.round((total_feedback.up / totalRated) * 100)}% positive)
          </span>
        )}
      </div>
      <div class="feedback-bars">
        {agentTypes.map((at) => {
          const fb = feedback_summary[at];
          const meta = agents[at] || {};
          const rated = fb.up + fb.down;
          const total = fb.total_findings || rated;
          const upPct = total > 0 ? (fb.up / total) * 100 : 0;
          const downPct = total > 0 ? (fb.down / total) * 100 : 0;
          const unratedPct = total > 0 ? Math.max(0, 100 - upPct - downPct) : 100;
          return (
            <div key={at} class="feedback-bar-row">
              <span class="feedback-bar-label">{meta.icon || '📋'} {meta.display_name || at}</span>
              <div class="feedback-bar-track">
                <div class="feedback-bar-up" style={{ width: `${upPct}%` }} />
                <div class="feedback-bar-down" style={{ width: `${downPct}%` }} />
                <div class="feedback-bar-unrated" style={{ width: `${unratedPct}%` }} />
              </div>
              <span class="feedback-bar-rate">{rated > 0 ? Math.round(fb.agreement_rate * 100) : '—'}% helpful</span>
              <span class="text-secondary feedback-bar-count">· {total > 0 ? Math.round((rated / total) * 100) : 0}% rated ({rated}/{total})</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Coverage Matrix: Heatmap of findings by section × agent ── */
function CoverageView() {
  const { t } = useI18n();
  const { agents } = useAgents();
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState('');
  const [coverage, setCoverage] = useState(null);
  const [covLoading, setCovLoading] = useState(false);
  const [covError, setCovError] = useState(null);

  useEffect(() => {
    listProjects('completed', 50).then((d) => setProjects(d.projects || [])).catch((e) => setCovError(e.message));
  }, []);

  const loadCoverage = useCallback((pid) => {
    if (!pid) return;
    setSelectedProject(pid);
    setCovLoading(true);
    setCovError(null);
    getAnalyticsCoverage(pid)
      .then(setCoverage)
      .catch((e) => { setCoverage(null); setCovError(e.message); })
      .finally(() => setCovLoading(false));
  }, []);

  return (
    <div class="page-section">
      <div class="coverage-controls">
        <select class="filter-select" value={selectedProject} onChange={(e) => loadCoverage(e.target.value)}>
          <option value="">{t('analytics.selectProject')}</option>
          {projects.map((p) => (
            <option key={p.project_id} value={p.project_id}>{p.name}</option>
          ))}
        </select>
      </div>
      {covLoading && <p>{t('common.loading')}</p>}
      {covError && <p class="status-message error">{covError}</p>}
      {coverage && coverage.sections?.length > 0 && (
        <div class="coverage-matrix-wrapper">
          <table class="coverage-table">
            <thead>
              <tr>
                <th class="coverage-section-header">Section</th>
                {coverage.agents.map((at) => {
                  const meta = agents[at] || {};
                  return <th key={at} class="coverage-agent-header">{meta.icon || ''} {meta.display_name || at}</th>;
                })}
              </tr>
            </thead>
            <tbody>
              {coverage.sections.map((section) => (
                <tr key={section}>
                  <td class="coverage-section-name" title={section}>{section}</td>
                  {coverage.agents.map((at) => {
                    const count = coverage.matrix[section]?.[at] || 0;
                    const intensity = Math.min(count / 4, 1);
                    return (
                      <td key={at} class="coverage-cell"
                          style={{ background: count > 0 ? `rgba(0, 168, 232, ${0.15 + intensity * 0.55})` : 'transparent' }}
                          title={`${count} finding(s)`}>
                        {count > 0 ? count : ''}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {coverage && coverage.sections?.length === 0 && (
        <p class="empty-state">No coverage data — findings may not have document references.</p>
      )}
    </div>
  );
}
