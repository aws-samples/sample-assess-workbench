import { useState, useEffect } from 'preact/hooks';
import { route } from 'preact-router';
import { getProject, deleteProject, getProjectDocument, getProjectReport, triggerReview, getProjectFeedback, submitFeedback } from '../api.js';
import { renderMarkdown } from '../markdown.js';
import { FindingCard } from '../components/finding-card.jsx';
import { Chat } from '../components/chat.jsx';
import { DeleteButton } from '../components/action-buttons.jsx';
import { JsonViewerModal } from '../components/json-viewer.jsx';
import { SplitPanel } from '../components/split-panel.jsx';
import { useAgents, useAgentLabel } from '../agent-context.jsx';
import { useI18n } from '../i18n-context.jsx';
import { useAuth } from '../auth.jsx';

function StatusBanner({ project, onReviewStarted, readOnly }) {
  const [starting, setStarting] = useState(false);
  const [bannerError, setBannerError] = useState(null);
  const { t } = useI18n();

  async function handleStartReview() {
    setStarting(true);
    setBannerError(null);
    try {
      const review = await triggerReview(project.project_id);
      if (onReviewStarted) onReviewStarted();
      route(`/projects/${project.project_id}/live/${review.review_id}`);
    } catch (e) {
      setBannerError(e.message);
      setStarting(false);
    }
  }

  if (project.status === 'completed') return null;

  if (project.status === 'pending') {
    return (
      <div class="status-banner pending">
        <span class="status-banner-icon">⏳</span>
        <span class="status-banner-text">{t('project.banner.pendingText')}</span>
        {!readOnly && (
          <button class="btn btn-primary btn-small" onClick={handleStartReview} disabled={starting}>
            {starting ? t('project.banner.starting') : t('project.banner.startReview')}
          </button>
        )}
        {bannerError && <span class="status-banner-error">{bannerError}</span>}
      </div>
    );
  }

  if (project.status === 'in_progress') {
    return (
      <div class="status-banner in-progress">
        <span class="status-banner-icon">🔄</span>
        <span class="status-banner-text">{t('project.banner.inProgressText')}</span>
        <a href={`/projects/${project.project_id}/live/${project.latest_review_id || ''}`} class="btn btn-primary btn-small">
          {t('project.banner.viewLive')}
        </a>
      </div>
    );
  }

  if (project.status === 'failed') {
    return (
      <div class="status-banner failed">
        <span class="status-banner-icon">❌</span>
        <span class="status-banner-text">{t('project.banner.failedText')}</span>
        {!readOnly && (
          <button class="btn btn-primary btn-small" onClick={handleStartReview} disabled={starting}>
            {starting ? t('project.banner.starting') : t('project.banner.retryReview')}
          </button>
        )}
        {bannerError && <span class="status-banner-error">{bannerError}</span>}
      </div>
    );
  }

  return null;
}

function parseFindings(project) {
  if (project.status !== 'completed' || !project.review?.result) return null;
  try {
    const result =
      typeof project.review.result === 'string'
        ? JSON.parse(project.review.result)
        : project.review.result;
    return result.reviews || null;
  } catch {
    return null;
  }
}

/** Build an agent order map from the review plan (group order → agent order). */
function planAgentOrder(project) {
  const plan = project?.review?.plan;
  if (!plan?.groups) return null;
  const order = {};
  let idx = 0;
  for (const group of plan.groups) {
    for (const agent of group.agents || []) {
      if (agent.agent_type && !(agent.agent_type in order)) {
        order[agent.agent_type] = idx++;
      }
    }
  }
  return Object.keys(order).length > 0 ? order : null;
}

export function ProjectDetailPage({ projectId }) {
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [expandAll, setExpandAll] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [showDoc, setShowDoc] = useState(null);
  const [showQuality, setShowQuality] = useState(false);
  const [feedbackMap, setFeedbackMap] = useState({});
  const [feedbackErrors, setFeedbackErrors] = useState({});
  const [feedbackWarning, setFeedbackWarning] = useState(false);
  const [reportMenu, setReportMenu] = useState(false);
  const [reportMarkdown, setReportMarkdown] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const { agents } = useAgents();
  const getAgentLabel = useAgentLabel();
  const { t } = useI18n();
  const { user } = useAuth();

  useEffect(() => {
    loadProject();
  }, [projectId]);

  // Close report dropdown on outside click or Escape
  useEffect(() => {
    if (!reportMenu) return;
    function handleClick(e) {
      if (!e.target.closest('.dropdown')) setReportMenu(false);
    }
    function handleKey(e) {
      if (e.key === 'Escape') setReportMenu(false);
    }
    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [reportMenu]);

  async function loadProject() {
    setLoading(true);
    setError(null);
    try {
      const data = await getProject(projectId);
      setProject(data);
      // Load feedback if review is completed
      if (data.status === 'completed') {
        try {
          const fb = await getProjectFeedback(projectId);
          const map = {};
          (fb.feedback || []).forEach((item) => {
            map[`${item.agent_type}:${item.finding_id}`] = item.value;
          });
          setFeedbackMap(map);
        } catch {
          // Non-critical — feedback just won't show, but indicate to user
          setFeedbackWarning(true);
        }
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleFeedback(agentType, findingId, value) {
    if (!value) {
      // Toggle off — remove from local state (no delete API needed, re-submitting overwrites)
      setFeedbackMap((prev) => {
        const next = { ...prev };
        delete next[`${agentType}:${findingId}`];
        return next;
      });
      return;
    }
    try {
      await submitFeedback(projectId, findingId, agentType, value);
      setFeedbackMap((prev) => ({ ...prev, [`${agentType}:${findingId}`]: value }));
    } catch (e) {
      const key = `${agentType}:${findingId}`;
      setFeedbackErrors((prev) => ({ ...prev, [key]: e.message || 'Feedback failed' }));
      setTimeout(() => setFeedbackErrors((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      }), 3000);
    }
  }

  /** Fetch report markdown (cached after first call). */
  async function fetchReport() {
    if (reportMarkdown) return reportMarkdown;
    setReportLoading(true);
    try {
      const data = await getProjectReport(projectId);
      setReportMarkdown(data.report);
      return data.report;
    } finally {
      setReportLoading(false);
    }
  }

  async function handlePreviewReport() {
    setReportMenu(false);
    try {
      await fetchReport();
      setShowReport(true);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleDownloadReport() {
    setReportMenu(false);
    try {
      const md = await fetchReport();
      const blob = new Blob([md], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${project?.name || 'report'}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleViewDocument() {
    try {
      const data = await getProjectDocument(projectId);
      const files = data.files || [];

      // If single binary file (PDF), open directly in browser
      if (files.length === 1 && files[0].download_url && !files[0].content) {
        window.open(files[0].download_url, '_blank');
        return;
      }

      // Open any binary files in separate tabs
      files.filter((f) => f.download_url && !f.content).forEach((f) => window.open(f.download_url, '_blank'));

      // Show text files in a modal
      const textFiles = files.filter((f) => f.content);
      if (textFiles.length > 0) {
        const combined = textFiles.map((f) => `=== ${f.filename} ===\n${f.content}`).join('\n\n');
        setShowDoc(combined);
      }
    } catch (e) {
      setError(t('error.loadDocument', { message: e.message }));
    }
  }

  async function handleDelete() {
    if (!confirm(t('project.delete.confirm', { name: project.name }))) {
      return;
    }
    setDeleting(true);
    try {
      await deleteProject(projectId);
      route('/');
    } catch (e) {
      setError(t('project.deleteFailed', { message: e.message }));
      setDeleting(false);
    }
  }

  if (loading) return <p class="status-message loading">{t('project.loading')}</p>;
  if (error) return <p class="status-message error">{error}</p>;
  if (!project) return null;

  const reviews = parseFindings(project);
  const planOrder = planAgentOrder(project);

  // Sort tabs by plan order (reflects actual review flow), fall back to registry sort_order.
  const tabs = reviews
    ? Object.keys(reviews)
        .filter((key) => reviews[key]?.findings)
        .sort((a, b) => {
          if (planOrder) return (planOrder[a] ?? 99) - (planOrder[b] ?? 99);
          return (agents[a]?.sort_order || 99) - (agents[b]?.sort_order || 99);
        })
    : [];

  // Default to first tab if activeTab not set or not in current tabs
  const currentTab = activeTab && tabs.includes(activeTab) ? activeTab : tabs[0] || null;

  const findings = reviews?.[currentTab]?.findings || [];
  const counts = {};
  tabs.forEach((key) => { counts[key] = reviews?.[key]?.findings?.length ?? '-'; });

  const agentLabel = (key) => getAgentLabel(key);
  const agentIcon = (key) => agents[key]?.icon || '🔍';

  return (
    <>
      {/* Compact project bar: name + status + tabs + actions */}
      <div class="project-bar">
        <div class="project-bar-left">
          <h2 class="project-bar-name" title={project.created_at ? `Created: ${new Date(project.created_at).toLocaleString()}` : ''}>
            {project.name || t('project.unnamed')}
          </h2>
          {project.status !== 'completed' && (
            <span class={`badge ${project.status}`}>{t(`project.status.${project.status}`) || project.status}</span>
          )}
        </div>
        <div class="project-bar-tabs">
          {tabs.map((key) => (
            <button
              key={key}
              class={`ptab ${currentTab === key ? 'active' : ''}`}
              onClick={() => setActiveTab(key)}
            >
              <span class="ptab-icon">{agentIcon(key)}</span>
              {agentLabel(key)}
              <span class="ptab-count">{counts[key]}</span>
            </button>
          ))}
        </div>
        <div class="project-bar-actions">
          {project.status === 'completed' && (
            <a href={`/projects/${projectId}/live/${project.latest_review_id || ''}`} class="btn btn-secondary btn-small">
              🔀 Review Flow
            </a>
          )}
          <button class="btn btn-secondary btn-small" onClick={handleViewDocument}>
            📄 {t('project.viewSpec')}
          </button>
          {reviews && (
            <div class="dropdown" style={{ position: 'relative' }}>
              <button
                class="btn btn-secondary btn-small"
                onClick={() => setReportMenu(!reportMenu)}
                aria-haspopup="true"
                aria-expanded={reportMenu}
              >
                📋 {t('project.report.menu')} ▾
              </button>
              {reportMenu && (
                <div class="dropdown-menu" role="menu">
                  <button role="menuitem" class="dropdown-item" onClick={handlePreviewReport} disabled={reportLoading}>
                    📋 {reportLoading ? t('project.report.loading') : t('project.report.preview')}
                  </button>
                  <button role="menuitem" class="dropdown-item" onClick={handleDownloadReport} disabled={reportLoading}>
                    📥 {reportLoading ? t('project.report.loading') : t('project.report.download')}
                  </button>
                  <button role="menuitem" class="dropdown-item" onClick={() => { setReportMenu(false); setShowJson(true); }}>
                    {'{ }'} JSON
                  </button>
                </div>
              )}
            </div>
          )}
          <DeleteButton onClick={handleDelete} deleting={deleting} disabled={user.readOnly} />
        </div>
      </div>

      <StatusBanner project={project} onReviewStarted={loadProject} readOnly={user.readOnly} />

      {/* Split Panel: Findings + Chat */}
      {currentTab && (
        <SplitPanel defaultSplit={50} className="split-panel--fixed">
          <div class="findings-panel">
              <div class="findings-toolbar">
                {currentTab === 'risk' && (
                  <a href={`/projects/${projectId}/heatmap`} class="btn btn-secondary btn-small">
                    📊 {t('project.heatmap')}
                  </a>
                )}
                <div class="findings-toolbar-right">
                  {reviews?.[currentTab]?.quality_scores && (
                    <span
                      class={`quality-score-badge ${showQuality ? 'active' : ''}`}
                      onClick={(e) => { e.stopPropagation(); setShowQuality(!showQuality); }}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setShowQuality(!showQuality)}
                      role="button"
                      tabIndex={0}
                      title="Click to show quality breakdown"
                    >
                      ⚖️ {reviews[currentTab].quality_scores.overall.toFixed(2)}
                    </span>
                  )}
                  {findings.length > 0 && (
                    <button
                      class="expand-toggle"
                      onClick={() => setExpandAll(!expandAll)}
                    >
                      {expandAll ? t('project.collapseAll') : t('project.expandAll')}
                    </button>
                  )}
                </div>
              </div>
              {showQuality && reviews?.[currentTab]?.quality_scores && (
                <div class="quality-breakdown">
                  {['completeness', 'specificity', 'actionability'].map((criterion) => {
                    const score = reviews[currentTab].quality_scores[criterion] || 0;
                    return (
                      <div key={criterion} class="quality-breakdown-row">
                        <span class="quality-breakdown-label">{criterion}</span>
                        <div class="quality-breakdown-bar">
                          <div class="quality-breakdown-fill" style={{ width: `${score * 100}%` }} />
                        </div>
                        <span class="quality-breakdown-value">{score.toFixed(2)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
              <div class="findings-scroll custom-scroll">
                {feedbackWarning && (
                  <p class="form-hint" style="color: var(--warning-color); padding: 0 1rem;">Could not load feedback &mdash; your prior ratings won&apos;t appear.</p>
                )}
                {findings.length === 0 ? (
                  <p class="empty-panel-text">
                    {reviews ? t('project.noFindings') : t('project.notCompleted')}
                  </p>
                ) : (
                  findings.map((f, i) => <FindingCard key={f.id || i} finding={f} agentType={currentTab} fieldDefinitions={(agents[currentTab]?.finding_schema?.fields) || {}} forceOpen={expandAll} feedbackValue={feedbackMap[`${currentTab}:${f.id}`] || null} feedbackError={feedbackErrors[`${currentTab}:${f.id}`] || null} onFeedback={(fid, val) => handleFeedback(currentTab, fid, val)} />)
                )}
              </div>
          </div>
          <Chat projectId={projectId} agent={currentTab} />
        </SplitPanel>
      )}
      {showJson && reviews && (
        <JsonViewerModal
          data={project.review.result}
          projectName={project.name}
          onClose={() => setShowJson(false)}
        />
      )}
      {showDoc && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
        <div class="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowDoc(null)} onKeyDown={(e) => e.key === 'Escape' && setShowDoc(null)} role="dialog" aria-modal="true">
          <div class="modal" style={{ maxWidth: '960px' }}>
            <div class="modal-header">
              <h3>📄 {project.name}</h3>
              <button class="modal-close" onClick={() => setShowDoc(null)}>✕</button>
            </div>
            <div class="modal-body">
              <pre class="document-viewer">{showDoc}</pre>
            </div>
          </div>
        </div>
      )}
      {showReport && reportMarkdown && (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
        <div class="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowReport(false)} onKeyDown={(e) => e.key === 'Escape' && setShowReport(false)} role="dialog" aria-modal="true">
          <div class="modal" style={{ maxWidth: '960px' }}>
            <div class="modal-header">
              <h3>📋 {t('project.report.title', { name: project.name })}</h3>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <button class="btn btn-secondary btn-small" onClick={handleDownloadReport}>📥 {t('project.report.download')}</button>
                <button class="modal-close" onClick={() => setShowReport(false)}>✕</button>
              </div>
            </div>
            <div class="modal-body report-preview" dangerouslySetInnerHTML={{ __html: renderMarkdown(reportMarkdown, 'docs') }} />
          </div>
        </div>
      )}
    </>
  );
}
