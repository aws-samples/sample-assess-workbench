import { useState, useEffect, useCallback, useMemo } from 'preact/hooks';
import { useAuth } from '../auth.jsx';
import { useAgents } from '../agent-context.jsx';
import {
  listBenchmarks, createBenchmark, getBenchmark, runBenchmark, deleteBenchmark, listProjects, listModels,
} from '../api.js';

export function BenchmarksPage() {
  const { user } = useAuth();
  const { agents } = useAgents();
  const isAdmin = user?.groups?.includes('admins');
  // Viewers may read benchmarks; run/delete/create remain gated on readOnly.
  const canView = isAdmin || user?.readOnly;

  const [benchmarks, setBenchmarks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    listBenchmarks()
      .then((d) => setBenchmarks(d.benchmarks || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  function viewDetail(id) {
    setSelectedId(id);
    setDetailLoading(true);
    getBenchmark(id)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setDetailLoading(false));
  }

  async function handleRun(id) {
    try {
      await runBenchmark(id);
      viewDetail(id);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleDelete(id, name) {
    if (!confirm(`Delete benchmark "${name}"? This removes all run results.`)) return;
    try {
      await deleteBenchmark(id);
      setSelectedId(null);
      setDetail(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!canView) {
    return <div class="page-section"><p class="empty-state">Admin access required to manage benchmarks.</p></div>;
  }

  if (selectedId && detail) {
    return (
      <BenchmarkDetail
        detail={detail}
        agents={agents}
        onBack={() => { setSelectedId(null); setDetail(null); }}
        onRun={() => handleRun(selectedId)}
        onDelete={() => handleDelete(detail.benchmark_id, detail.name)}
        onRefresh={() => viewDetail(selectedId)}
        loading={detailLoading}
        readOnly={user.readOnly}
      />
    );
  }

  return (
    <div>
      <div class="page-section">
        <div class="page-header">
          <h2>🔬 Benchmarks</h2>
          <div class="page-actions">
            <button class="btn btn-primary btn-small" onClick={() => setShowCreate(true)} disabled={user.readOnly}>+ New Benchmark</button>
          </div>
        </div>
        {error && <div class="status-message error">{error}</div>}
        {showCreate && (
          <CreateBenchmarkForm
            agents={agents}
            onCreated={(b) => { setShowCreate(false); refresh(); viewDetail(b.benchmark_id); }}
            onCancel={() => setShowCreate(false)}
          />
        )}
        {loading ? <p>Loading...</p> : benchmarks.length === 0 ? (
          <p class="empty-state">No benchmarks yet. Create one to compare models.</p>
        ) : (
          <div class="benchmarks-list">
            {benchmarks.map((b) => (
              <div key={b.benchmark_id} class="benchmark-card" role="button" tabIndex={0} onClick={() => viewDetail(b.benchmark_id)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && viewDetail(b.benchmark_id)}>
                <div class="benchmark-card-header">
                  <span class="benchmark-card-name">{b.name}</span>
                  <span class={`badge ${b.status}`}>{b.status}</span>
                </div>
                <div class="benchmark-card-meta">
                  <span>{agents[b.agent_type]?.icon || '📋'} {agents[b.agent_type]?.display_name || b.agent_type}</span>
                  <span>{new Date(b.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Create Benchmark Form ── */
function CreateBenchmarkForm({ agents, onCreated, onCancel }) {
  const [name, setName] = useState('');
  const [projectId, setProjectId] = useState('');
  const [agentType, setAgentType] = useState('');
  const [configs, setConfigs] = useState([{ label: '', model_id: '', depth: 'standard' }]);
  const [projects, setProjects] = useState([]);
  const [models, setModels] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    listProjects('completed', 50).then((d) => setProjects(d.projects || [])).catch((e) => setError(e.message));
    listModels().then((d) => setModels(d.models || [])).catch((e) => setError(e.message));
  }, []);

  // Group models by provider, then source within each provider
  const modelGroups = useMemo(() => {
    const byProvider = {};
    models.forEach((m) => {
      const provider = m.provider_name || 'Other';
      if (!byProvider[provider]) byProvider[provider] = {};
      const source = m.source === 'cross-region' ? 'cross-region' : 'foundation';
      if (!byProvider[provider][source]) byProvider[provider][source] = [];
      byProvider[provider][source].push(m);
    });
    // Sort providers alphabetically
    return Object.entries(byProvider).sort(([a], [b]) => a.localeCompare(b));
  }, [models]);

  function addConfig() {
    setConfigs([...configs, { label: '', model_id: '', depth: 'standard' }]);
  }

  function updateConfig(i, field, value) {
    const updated = [...configs];
    updated[i] = { ...updated[i], [field]: value };
    // Auto-fill label from model name when model is selected
    if (field === 'model_id' && !updated[i].label) {
      const model = models.find((m) => m.model_id === value);
      if (model) updated[i].label = model.model_name;
    }
    setConfigs(updated);
  }

  function removeConfig(i) {
    if (configs.length <= 1) return;
    setConfigs(configs.filter((_, idx) => idx !== i));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim() || !projectId || !agentType || configs.some((c) => !c.label || !c.model_id)) {
      setError('Fill in all required fields.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const result = await createBenchmark(name.trim(), projectId, agentType, configs);
      onCreated(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const agentTypes = Object.keys(agents).filter((at) => agents[at]?.has_review_agent);

  return (
    <form class="create-form benchmark-create" onSubmit={handleSubmit}>
      {error && <div class="status-message error">{error}</div>}
      <div class="form-group">
        <label>Benchmark Name
        <input value={name} onInput={(e) => setName(e.target.value)} placeholder="e.g. Sonnet 4 vs Haiku — Architecture" />
        </label>
      </div>
      <div class="form-row">
        <div class="form-group" style="flex:1">
          <label>Source Project
          <select class="filter-select" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Select a completed project...</option>
            {projects.map((p) => <option key={p.project_id} value={p.project_id}>{p.name}</option>)}
          </select>
          </label>
        </div>
        <div class="form-group" style="flex:1">
          <label>Agent Type
          <select class="filter-select" value={agentType} onChange={(e) => setAgentType(e.target.value)}>
            <option value="">Select agent...</option>
            {agentTypes.map((at) => (
              <option key={at} value={at}>{agents[at]?.icon} {agents[at]?.display_name || at}</option>
            ))}
          </select>
          </label>
        </div>
      </div>
      <div class="form-group">
        <span class="form-label">Configurations</span>
        {configs.map((cfg, i) => (
          <div key={i} class="config-row">
            <input placeholder="Label" value={cfg.label}
              onInput={(e) => updateConfig(i, 'label', e.target.value)} style="flex:1" />
            <select class="filter-select" value={cfg.model_id}
              onChange={(e) => updateConfig(i, 'model_id', e.target.value)} style="flex:2">
              <option value="">Select model...</option>
              {modelGroups.map(([provider, sources]) => (
                ['cross-region', 'foundation'].map((source) => {
                  const list = sources[source];
                  if (!list || list.length === 0) return null;
                  return (
                    <optgroup key={`${provider}-${source}`} label={`${provider} (${source})`}>
                      {list.map((m) => (
                        <option key={m.model_id} value={m.model_id}>{m.model_name}</option>
                      ))}
                    </optgroup>
                  );
                })
              ))}
            </select>
            <select value={cfg.depth} onChange={(e) => updateConfig(i, 'depth', e.target.value)} class="filter-select">
              <option value="quick">Quick</option>
              <option value="standard">Standard</option>
              <option value="thorough">Thorough</option>
            </select>
            {configs.length > 1 && (
              <button type="button" class="btn btn-secondary btn-small" onClick={() => removeConfig(i)}>✕</button>
            )}
          </div>
        ))}
        <button type="button" class="btn btn-secondary btn-small" onClick={addConfig} style="margin-top:0.5rem">
          + Add Configuration
        </button>
        <p class="model-hint">Cross-region models (e.g. us.anthropic.*) route to the nearest available region. Foundation models run in your account&#39;s region only.</p>
      </div>
      <div class="page-actions">
        <button type="submit" class="btn btn-primary btn-small" disabled={submitting}>
          {submitting ? 'Creating...' : 'Create Benchmark'}
        </button>
        <button type="button" class="btn btn-secondary btn-small" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

/* ── Benchmark Detail: results view ── */
function BenchmarkDetail({ detail, agents, onBack, onRun, onDelete, onRefresh, loading: _loading, readOnly }) {
  const meta = agents[detail.agent_type] || {};
  const runs = detail.runs || [];
  const hasResults = runs.some((r) => r.status === 'completed');
  const isRunning = detail.status === 'running';

  // Auto-refresh while running
  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(onRefresh, 5000);
    return () => clearInterval(interval);
  }, [isRunning, onRefresh]);

  return (
    <div>
      <div class="page-section">
        <div class="page-header">
          <div>
            <button class="btn btn-secondary btn-small" onClick={onBack} style="margin-right:0.75rem">← Back</button>
            <span style="font-size:1.1rem;font-weight:600">{detail.name}</span>
            <span class={`badge ${detail.status}`} style="margin-left:0.75rem">{detail.status}</span>
          </div>
          <div class="page-actions">
            {detail.status !== 'running' && (
              <button class="btn btn-primary btn-small" onClick={onRun} disabled={readOnly}>
                {hasResults ? '🔄 Re-run' : '▶ Run Benchmark'}
              </button>
            )}
            <button class="btn btn-danger btn-small" onClick={onDelete} disabled={readOnly}>🗑 Delete</button>
          </div>
        </div>
        <div class="info-grid" style="margin-bottom:1rem">
          <div class="info-item">
            <span class="label">Agent</span>
            <span>{meta.icon || '📋'} {meta.display_name || detail.agent_type}</span>
          </div>
          <div class="info-item">
            <span class="label">Configurations</span>
            <span>{detail.configurations?.length || 0}</span>
          </div>
          <div class="info-item">
            <span class="label">Created</span>
            <span>{new Date(detail.created_at).toLocaleString()}</span>
          </div>
        </div>
        {isRunning && (
          <div class="status-message loading">
            Benchmark running... {runs.filter((r) => r.status === 'completed').length}/{detail.configurations?.length || 0} configs complete. Auto-refreshing.
          </div>
        )}
        {detail.status === 'failed' && detail.error_message && (
          <div class="status-message error">
            Benchmark failed: {detail.error_message}
          </div>
        )}
      </div>

      {(runs.length > 0 || isRunning) && (
        <div class="page-section">
          <h3 style="margin-bottom:1rem">Results Comparison</h3>
          <div class="benchmark-results-grid">
            {(detail.configurations || []).map((cfg) => {
              const run = runs.find((r) => r.config_id === cfg.config_id);

              if (!run) {
                // Config hasn't completed yet
                return (
                  <div key={cfg.config_id} class="benchmark-result-card benchmark-result-running">
                    <h4>{cfg.label || cfg.config_id}</h4>
                    <div class="benchmark-model-id">{cfg.model_id || ''}</div>
                    {isRunning ? (
                      <div class="benchmark-running-indicator">
                        <div class="thinking-dots"><span /><span /><span /></div>
                        <span>Running...</span>
                      </div>
                    ) : (
                      <div class="benchmark-pending-label">Pending</div>
                    )}
                  </div>
                );
              }

              if (run.status === 'failed') {
                return (
                  <div key={run.config_id} class="benchmark-result-card benchmark-result-failed">
                    <h4>{cfg.label || run.config_id}</h4>
                    <div class="benchmark-model-id">{cfg.model_id || ''}</div>
                    <div class="benchmark-error">
                      <span class="benchmark-error-icon">✕</span>
                      <span class="benchmark-error-label">Failed</span>
                    </div>
                    <div class="benchmark-error-message">{run.error || 'Unknown error'}</div>
                  </div>
                );
              }

              const qs = run.quality_scores || {};
              const metrics = run.metrics || {};
              const findings = run.findings || [];
              const bySeverity = { critical: 0, high: 0, medium: 0, low: 0 };
              findings.forEach((f) => { const s = (f.severity || '').toLowerCase(); if (bySeverity[s] !== undefined) bySeverity[s]++; });

              return (
                <div key={run.config_id} class="benchmark-result-card">
                  <h4>{cfg.label || run.config_id}</h4>
                  <div class="benchmark-model-id">{cfg.model_id || ''}</div>

                  <div class="benchmark-score-section">
                    <div class="benchmark-score-main">{(qs.overall || 0).toFixed(2)}</div>
                    <div class="benchmark-score-label">Quality Score</div>
                    <div class="benchmark-score-breakdown">
                      {['completeness', 'specificity', 'actionability'].map((c) => (
                        <div key={c} class="benchmark-score-row">
                          <span>{c}</span>
                          <div class="quality-breakdown-bar">
                            <div class="quality-breakdown-fill" style={{ width: `${(qs[c] || 0) * 100}%` }} />
                          </div>
                          <span>{(qs[c] || 0).toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div class="benchmark-findings-summary">
                    <span class="benchmark-finding-total">{findings.length} findings</span>
                    {bySeverity.critical > 0 && <span class="severity-badge critical">{bySeverity.critical} critical</span>}
                    {bySeverity.high > 0 && <span class="severity-badge high">{bySeverity.high} high</span>}
                    {bySeverity.medium > 0 && <span class="severity-badge medium">{bySeverity.medium} med</span>}
                    {bySeverity.low > 0 && <span class="severity-badge low">{bySeverity.low} low</span>}
                  </div>

                  <div class="benchmark-metrics">
                    <div class="benchmark-metric">
                      <span class="label">Tokens</span>
                      <span>{(metrics.total_tokens || 0).toLocaleString()}</span>
                    </div>
                    <div class="benchmark-metric">
                      <span class="label">Duration</span>
                      <span>{(metrics.total_duration_s || 0).toFixed(1)}s</span>
                    </div>
                    <div class="benchmark-metric">
                      <span class="label">Latency</span>
                      <span>{((metrics.model_latency_ms || 0) / 1000).toFixed(1)}s</span>
                    </div>
                    {metrics.estimated_cost_usd != null && (
                      <div class="benchmark-metric">
                        <span class="label">Est. Cost</span>
                        <span>${(metrics.estimated_cost_usd || 0).toFixed(4)}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
