import { useState, useEffect } from 'preact/hooks';
import { listContexts, createContext, deleteContext, getContextContent, updateContextContent } from '../api.js';
import { DeleteButton, EditButton, SaveButton, CancelButton } from '../components/action-buttons.jsx';
import { useI18n } from '../i18n-context.jsx';
import { useAuth } from '../auth.jsx';

export function ContextsPage() {
  const { user } = useAuth();
  const [contexts, setContexts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [file, setFile] = useState(null);
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState(null);
  const [editing, setEditing] = useState(null);
  const { t } = useI18n();

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const data = await listContexts();
      setContexts(data.contexts || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setStatus(null);
    try {
      const ctx = await createContext(name.trim(), description.trim());
      if (file && ctx.upload_url) {
        const res = await fetch(ctx.upload_url, {
          method: 'PUT',
          body: file,
          headers: { 'Content-Type': 'text/markdown' },
        });
        if (!res.ok) throw new Error('Upload failed');
      }
      setName('');
      setDescription('');
      setFile(null);
      setShowCreate(false);
      setStatus({ type: 'success', message: t('context.created') });
      await load();
    } catch (err) {
      setStatus({ type: 'error', message: err.message });
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(contextId, contextName) {
    if (!confirm(t('context.deleteConfirm', { name: contextName }))) return;
    try {
      await deleteContext(contextId);
      if (editing?.contextId === contextId) setEditing(null);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleEdit(contextId) {
    if (editing?.contextId === contextId) {
      setEditing(null);
      return;
    }
    try {
      const data = await getContextContent(contextId);
      setEditing({ contextId, content: data.content || '', saving: false });
    } catch (e) {
      setStatus({ type: 'error', message: e.message });
    }
  }

  async function handleSave() {
    if (!editing) return;
    setEditing((prev) => ({ ...prev, saving: true }));
    try {
      await updateContextContent(editing.contextId, editing.content);
      setStatus({ type: 'success', message: t('context.updated') });
      setEditing(null);
    } catch (e) {
      setStatus({ type: 'error', message: e.message });
      setEditing((prev) => ({ ...prev, saving: false }));
    }
  }

  return (
    <section class="page-section">
      <div class="page-header">
        <h2>{t('context.title')}</h2>
        <button class="btn btn-primary" onClick={() => setShowCreate(!showCreate)} disabled={user.readOnly}>
          {showCreate ? t('context.cancelCreate') : t('context.newContext')}
        </button>
      </div>

      <p class="subtitle" style="margin-bottom: 1.5rem;">
        {t('context.subtitle')}
      </p>

      {status && <div class={`status-message ${status.type}`}>{status.message}</div>}

      {showCreate && (
        <div class="create-inline">
          <form onSubmit={handleCreate}>
            <div class="form-group">
              <label for="ctx-name">{t('context.nameLabel')}</label>
              <input
                id="ctx-name" type="text" value={name}
                onInput={(e) => setName(e.target.value)}
                placeholder={t('context.namePlaceholder')}
                required
              />
            </div>
            <div class="form-group">
              <label for="ctx-desc">{t('context.descLabel')}</label>
              <textarea
                id="ctx-desc" value={description}
                onInput={(e) => setDescription(e.target.value)}
                placeholder={t('context.descPlaceholder')}
                rows={2}
              />
            </div>
            <div class="form-group">
              <label for="ctx-file">{t('context.fileLabel')}</label>
              <input
                id="ctx-file" type="file"
                onChange={(e) => setFile(e.target.files[0])}
                accept=".md,.txt"
              />
            </div>
            <button type="submit" class="btn btn-primary" disabled={!name.trim() || !file || creating}>
              {creating ? t('context.creating') : t('context.createUpload')}
            </button>
          </form>
        </div>
      )}

      {loading && <p class="status-message loading">{t('context.loading')}</p>}
      {error && <p class="status-message error">{error}</p>}

      {!loading && contexts.length === 0 && !showCreate && (
        <div class="empty-state">
          <p>{t('context.empty')}</p>
        </div>
      )}

      <div class="contexts-list">
        {contexts.map((c) => (
          <div key={c.context_id} class="context-card-wrapper">
            <div class="context-card">
              <div class="context-card-body">
                <h3>{c.name}</h3>
                {c.description && <p class="context-desc">{c.description}</p>}
                <span class="context-meta">
                  {c.context_id} · {c.created_at ? new Date(c.created_at).toLocaleDateString() : ''}
                </span>
              </div>
              <div class="context-card-actions">
                <EditButton
                  onClick={() => handleEdit(c.context_id)}
                  active={editing?.contextId === c.context_id}
                />
                <DeleteButton
                  onClick={() => handleDelete(c.context_id, c.name)}
                  disabled={user.readOnly}
                />
              </div>
            </div>
            {editing?.contextId === c.context_id && (
              <div class="context-editor">
                <textarea
                  class="context-editor-textarea"
                  value={editing.content}
                  onInput={(e) => setEditing((prev) => ({ ...prev, content: e.target.value }))}
                  rows={20}
                />
                <div class="context-editor-actions">
                  <SaveButton onClick={handleSave} saving={editing.saving} disabled={user.readOnly} />
                  <CancelButton onClick={() => setEditing(null)} />
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
