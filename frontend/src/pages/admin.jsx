import { useState, useEffect } from 'preact/hooks';
import { useI18n } from '../i18n-context.jsx';
import { useAuth } from '../auth.jsx';
import { getAdminRegistry, updateAdminRegistry } from '../api.js';

export function AdminPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.groups?.includes('admins');
  // Viewers may read this admin view; write controls remain gated on readOnly.
  const canView = isAdmin || user?.readOnly;
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingAgent, setEditingAgent] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  useEffect(() => {
    if (!canView) { setLoading(false); return; }
    getAdminRegistry()
      .then((d) => setAgents(d.agents || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [canView]);

  function startEdit(agent) {
    setEditingAgent(agent.agent_type);
    // Parse finding_schema and judge_defaults if they're JSON strings
    let fs = agent.finding_schema;
    let jd = agent.judge_defaults;
    let parseWarning = null;
    if (typeof fs === 'string') {
      try { fs = JSON.parse(fs); } catch { parseWarning = 'finding_schema'; }
    }
    if (typeof jd === 'string') {
      try { jd = JSON.parse(jd); } catch { parseWarning = parseWarning ? 'finding_schema, judge_defaults' : 'judge_defaults'; }
    }
    setEditForm({
      display_name: agent.display_name || '',
      icon: agent.icon || '',
      color: agent.color || '',
      sort_order: agent.sort_order ?? 0,
      enabled: agent.enabled !== false,
      coach_enabled: typeof jd === 'object' && jd?.coach_enabled != null ? String(jd.coach_enabled) : '',
      quality_threshold: typeof jd === 'object' && jd?.quality_threshold != null ? String(jd.quality_threshold) : '',
      max_iterations: typeof jd === 'object' ? (jd?.max_iterations ?? 3) : 3,
      default_depth: agent.default_depth || '',
      description: agent.description || '',
      display_strategy: (typeof fs === 'object' ? fs?.display_strategy : '') || '',
      coach_guidance: agent.coach_guidance || '',
      parseWarning,
    });
    setStatusMsg('');
    if (parseWarning) {
      setStatusMsg(`⚠ Malformed JSON in ${parseWarning} — some fields may be missing`);
    }
  }

  async function handleSave() {
    setSaving(true);
    setStatusMsg('');
    try {
      // Reconstruct judge_defaults — only include fields with explicit values
      const jd = {};
      if (editForm.coach_enabled !== '') {
        jd.coach_enabled = editForm.coach_enabled === 'true';
      }
      if (editForm.quality_threshold !== '') {
        jd.quality_threshold = parseFloat(editForm.quality_threshold) || 0.8;
      }
      if (editForm.coach_enabled !== '') {
        jd.max_iterations = parseInt(editForm.max_iterations) || 3;
      }
      const judgeDefaults = Object.keys(jd).length > 0 ? JSON.stringify(jd) : '';

      const updates = {
        display_name: editForm.display_name,
        icon: editForm.icon,
        color: editForm.color,
        sort_order: parseInt(editForm.sort_order) || 0,
        enabled: editForm.enabled,
        description: editForm.description,
        judge_defaults: judgeDefaults,
        default_depth: editForm.default_depth || '',
        coach_guidance: editForm.coach_guidance,
      };

      const updated = await updateAdminRegistry(editingAgent, updates);
      // Update local state
      setAgents((prev) => prev.map((a) => a.agent_type === editingAgent ? { ...a, ...updated } : a));
      setStatusMsg(t('admin.saved'));
      setEditingAgent(null);
    } catch (e) {
      setStatusMsg(t('admin.saveFailed', { message: e.message }));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div class="page-section"><p>{t('admin.loading')}</p></div>;
  if (!canView) return <div class="page-section"><p class="empty-state">{t('admin.noAccess')}</p></div>;
  if (error) return <div class="page-section status-message error">{error}</div>;

  return (
    <div class="page-section">
      <div class="page-header">
        <h2>{t('admin.title')}</h2>
      </div>
      {statusMsg && <div class="status-message success" style="margin-bottom:1rem">{statusMsg}</div>}
      <table class="admin-table">
        <thead>
          <tr>
            <th>{t('admin.agent')}</th>
            <th>{t('admin.status')}</th>
            <th>{t('admin.displayStrategy')}</th>
            <th>
              <span class="header-with-tooltip">
                {t('admin.coach')} <span class="tooltip-icon">ⓘ</span>
                <span class="tooltip-text">{t('admin.coachTooltip')}</span>
              </span>
            </th>
            <th>
              <span class="header-with-tooltip">
                {t('admin.threshold')} <span class="tooltip-icon">ⓘ</span>
                <span class="tooltip-text">{t('admin.thresholdTooltip')}</span>
              </span>
            </th>
            <th>
              <span class="header-with-tooltip">
                {t('admin.depth')} <span class="tooltip-icon">ⓘ</span>
                <span class="tooltip-text">{t('admin.depthTooltip')}</span>
              </span>
            </th>
            <th>
              <span class="header-with-tooltip">
                {t('admin.order')} <span class="tooltip-icon">ⓘ</span>
                <span class="tooltip-text">{t('admin.orderTooltip')}</span>
              </span>
            </th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => {
            let fs = agent.finding_schema;
            let jd = agent.judge_defaults;
            let rowParseWarning = null;
            if (typeof fs === 'string') {
              try { fs = JSON.parse(fs); } catch { rowParseWarning = 'finding_schema'; }
            }
            if (typeof jd === 'string') {
              try { jd = JSON.parse(jd); } catch { rowParseWarning = rowParseWarning ? 'finding_schema, judge_defaults' : 'judge_defaults'; }
            }
            const isEditing = editingAgent === agent.agent_type;

            return (
              <>
              <tr key={agent.agent_type} class={isEditing ? 'admin-row-editing' : ''}>
                <td>{agent.icon} {agent.display_name || agent.agent_type}</td>
                <td>
                  {isEditing ? (
                    <label class="toggle-label">
                      <input type="checkbox" checked={editForm.enabled}
                        disabled={user.readOnly}
                        onChange={(e) => setEditForm({ ...editForm, enabled: e.target.checked })} />
                      {editForm.enabled ? t('admin.enabled') : t('admin.disabled')}
                    </label>
                  ) : (
                    <span class={`badge ${agent.enabled !== false ? 'success' : 'danger'}`}>
                      {agent.enabled !== false ? t('admin.enabled') : t('admin.disabled')}
                    </span>
                  )}
                </td>
                <td>{typeof fs === 'object' ? (fs?.display_strategy || '—') : <span class="badge danger" title={`Malformed JSON in ${rowParseWarning}`}>{t('admin.parseError')}</span>}</td>
                <td>
                  {isEditing ? (
                    <select class="admin-input-sm"
                      value={editForm.coach_enabled}
                      disabled={user.readOnly}
                      onChange={(e) => setEditForm({ ...editForm, coach_enabled: e.target.value })}>
                      <option value="">{t('admin.plannerDecides')}</option>
                      <option value="true">{t('admin.coachOn')}</option>
                      <option value="false">{t('admin.coachOff')}</option>
                    </select>
                  ) : (
                    jd?.coach_enabled != null ? (jd.coach_enabled ? t('admin.coachOn') : t('admin.coachOff')) : '—'
                  )}
                </td>
                <td>
                  {isEditing ? (
                    <select class="admin-input-sm"
                      value={editForm.quality_threshold}
                      disabled={user.readOnly}
                      onChange={(e) => setEditForm({ ...editForm, quality_threshold: e.target.value })}>
                      <option value="">{t('admin.plannerDecides')}</option>
                      {[0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0].map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  ) : (
                    jd?.quality_threshold != null ? jd.quality_threshold : '—'
                  )}
                </td>
                <td>
                  {isEditing ? (
                    <select class="admin-input-sm"
                      value={editForm.default_depth}
                      disabled={user.readOnly}
                      onChange={(e) => setEditForm({ ...editForm, default_depth: e.target.value })}>
                      <option value="">{t('admin.plannerDecides')}</option>
                      <option value="quick">{t('admin.depthQuick')}</option>
                      <option value="standard">{t('admin.depthStandard')}</option>
                      <option value="thorough">{t('admin.depthThorough')}</option>
                    </select>
                  ) : (
                    agent.default_depth || '—'
                  )}
                </td>
                <td>
                  {isEditing ? (
                    <input type="number" min="0" max="99" class="admin-input-sm"
                      value={editForm.sort_order}
                      disabled={user.readOnly}
                      onChange={(e) => setEditForm({ ...editForm, sort_order: e.target.value })} />
                  ) : (
                    agent.sort_order ?? '—'
                  )}
                </td>
                <td>
                  {isEditing ? (
                    <div class="admin-actions">
                      {/* Read-only users can open the editor to inspect detail,
                          but there's nothing to save — show Close only. */}
                      {!user.readOnly && (
                        <button class="btn btn-primary btn-small" onClick={handleSave} disabled={saving}>
                          {saving ? t('admin.saving') : t('admin.save')}
                        </button>
                      )}
                      <button class="btn btn-secondary btn-small" onClick={() => setEditingAgent(null)}>
                        {user.readOnly ? t('common.close') : t('admin.cancel')}
                      </button>
                    </div>
                  ) : (
                    <button class="btn btn-secondary btn-small" onClick={() => startEdit(agent)}>
                      {user.readOnly ? t('common.view') : t('common.edit')}
                    </button>
                  )}
                </td>
              </tr>
              {isEditing && (
                <tr class="admin-row-editing admin-row-expansion">
                  <td colSpan="8">
                    <div class="coach-guidance-section">
                      <label class="coach-guidance-label">
                        <span class="header-with-tooltip">
                          {t('admin.description')} <span class="tooltip-icon">ⓘ</span>
                          <span class="tooltip-text">{t('admin.descriptionTooltip')}</span>
                        </span>
                      </label>
                      <textarea
                        class="coach-guidance-textarea"
                        rows="3"
                        value={editForm.description}
                        placeholder={t('admin.descriptionPlaceholder')}
                        readOnly={user.readOnly}
                        onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                      />
                    </div>
                    <div class="coach-guidance-section" style="margin-top:1rem">
                      <label class="coach-guidance-label">
                        <span class="header-with-tooltip">
                          {t('admin.coachGuidance')} <span class="tooltip-icon">ⓘ</span>
                          <span class="tooltip-text">{t('admin.coachGuidanceTooltip')}</span>
                        </span>
                        {!user.readOnly && (
                          <button class="btn btn-secondary btn-small" style="margin-left:0.5rem"
                            onClick={() => {
                              const input = document.createElement('input');
                              input.type = 'file';
                              input.accept = '.md,.txt';
                              input.onchange = (ev) => {
                                const file = ev.target.files[0];
                                if (!file) return;
                                const reader = new FileReader();
                                reader.onload = (e) => setEditForm({ ...editForm, coach_guidance: e.target.result });
                                reader.readAsText(file);
                              };
                              input.click();
                            }}>
                            {t('admin.uploadFile')}
                          </button>
                        )}
                      </label>
                      <textarea
                        class="coach-guidance-textarea"
                        rows="10"
                        value={editForm.coach_guidance}
                        placeholder={t('admin.coachGuidancePlaceholder')}
                        readOnly={user.readOnly}
                        onChange={(e) => setEditForm({ ...editForm, coach_guidance: e.target.value })}
                      />
                    </div>
                    {agent.chat_agent_config && (
                      <div class="coach-guidance-section" style="margin-top:1rem">
                        <label class="coach-guidance-label">
                          <span class="header-with-tooltip">
                            {t('admin.chatAgentPrompt')} <span class="tooltip-icon">ⓘ</span>
                            <span class="tooltip-text">{t('admin.chatAgentPromptTooltip')}</span>
                          </span>
                          <span class="badge" style="margin-left:0.5rem">{agent.chat_agent_config.agent_type}</span>
                        </label>
                        <textarea
                          class="coach-guidance-textarea"
                          rows="10"
                          value={agent.chat_agent_config.prompt_template || ''}
                          readOnly
                        />
                      </div>
                    )}
                  </td>
                </tr>
              )}
              </>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
