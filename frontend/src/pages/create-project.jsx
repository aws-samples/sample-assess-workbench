import { useState, useEffect } from 'preact/hooks';
import { route } from 'preact-router';
import { createProject, uploadProjectFiles, triggerReview, listContexts } from '../api.js';
import { useAuth } from '../auth.jsx';
import { useI18n } from '../i18n-context.jsx';

const ACCEPTED_TYPES = '.pdf,.txt,.md,.doc,.docx,.png,.jpg,.jpeg,.svg';
const MAX_FILES = 10;

export function CreateProjectPage() {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [contextId, setContextId] = useState('');
  const [contexts, setContexts] = useState([]);
  const [contextWarning, setContextWarning] = useState(false);
  const [files, setFiles] = useState([]);
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const { t } = useI18n();
  const { user } = useAuth();

  // readOnly is role-derived (viewer = not admin/users), so it fully captures
  // "cannot create" — no separate viewer check needed.
  const canCreate = !user.readOnly;

  useEffect(() => {
    listContexts().then((data) => setContexts(data.contexts || [])).catch(() => setContextWarning(true));
  }, []);

  function addFiles(newFiles) {
    const fileArray = Array.from(newFiles);
    setFiles((prev) => {
      const combined = [...prev, ...fileArray];
      return combined.slice(0, MAX_FILES);
    });
  }

  function removeFile(index) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim() || files.length === 0) return;
    setCreating(true);
    setStatus({ type: 'loading', message: t('create.statusCreating') });
    try {
      const project = await createProject(name.trim(), description.trim(), contextId || undefined, files);

      setStatus({ type: 'loading', message: t('create.statusUploading', { count: files.length }) });
      await uploadProjectFiles(project, files);

      setStatus({ type: 'loading', message: t('create.statusStarting') });
      const review = await triggerReview(project.project_id);

      route(`/projects/${project.project_id}/live/${review.review_id}`);
    } catch (err) {
      setStatus({ type: 'error', message: err.message });
      setCreating(false);
    }
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function fileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    if (ext === 'pdf') return '📕';
    if (['png', 'jpg', 'jpeg', 'svg', 'gif'].includes(ext)) return '🖼️';
    if (['md', 'markdown'].includes(ext)) return '📝';
    return '📄';
  }

  return (
    <section class="page-section">
      <h2>{t('create.title')}</h2>

      {!canCreate && (
        <div class="status-message warning" style="margin-bottom: 1rem;">
          You have read-only (viewer) access — you can explore this screen, but
          creating projects is disabled. Sign in with an email/password admin
          account for full access.
        </div>
      )}

      <form class="create-form" onSubmit={handleSubmit}>
        <div class="form-group">
          <label for="project-name">{t('create.nameLabel')}</label>
          <input
            id="project-name" type="text" value={name}
            onInput={(e) => setName(e.target.value)}
            placeholder={t('create.namePlaceholder')}
            required
          />
        </div>
        <div class="form-group">
          <label for="project-desc">{t('create.descLabel')}</label>
          <textarea
            id="project-desc" value={description}
            onInput={(e) => setDescription(e.target.value)}
            placeholder={t('create.descPlaceholder')}
            rows={2}
          />
        </div>
        <div class="form-group">
          <label for="project-context">{t('create.contextLabel')}</label>
          <select
            id="project-context"
            class="filter-select"
            value={contextId}
            onChange={(e) => setContextId(e.target.value)}
          >
            <option value="">{t('create.contextNone')}</option>
            {contexts.map((c) => (
              <option key={c.context_id} value={c.context_id}>{c.name}</option>
            ))}
          </select>
          <p class="form-hint">
            {t('create.contextHint')}
            <a href="/contexts"> {t('create.contextManage')}</a>
          </p>
          {contextWarning && <p class="form-hint" style="color: var(--warning-color)">Could not load organizational contexts.</p>}
        </div>

        {/* Multi-file upload area */}
        <div class="form-group">
          <label>{t('create.docsLabel')}</label>
          <div
            class={`file-dropzone ${dragOver ? 'file-dropzone--active' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById('doc-upload').click()}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && document.getElementById('doc-upload').click()}
            role="button"
            tabIndex={0}
            aria-label={t('create.dropzone')}
          >
            <input
              id="doc-upload" type="file" multiple
              onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }}
              accept={ACCEPTED_TYPES}
              style="display:none"
            />
            <div class="file-dropzone-content">
              <span class="file-dropzone-icon">📎</span>
              <span>{t('create.dropzone')}</span>
              <span class="file-dropzone-hint">{t('create.dropzoneHint', { max: MAX_FILES })}</span>
            </div>
          </div>

          {files.length > 0 && (
            <ul class="file-list">
              {files.map((f, i) => (
                <li key={i} class="file-list-item">
                  <span class="file-list-icon">{fileIcon(f.name)}</span>
                  <span class="file-list-name">{f.name}</span>
                  <span class="file-list-size">{formatSize(f.size)}</span>
                  <button
                    type="button" class="file-list-remove"
                    onClick={(e) => { e.stopPropagation(); removeFile(i); }}
                    aria-label={`Remove ${f.name}`}
                  >✕</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button
          type="submit" class="btn btn-primary"
          disabled={!canCreate || !name.trim() || files.length === 0 || creating}
        >
          {creating ? t('create.creating') : t('create.submit')}
        </button>
      </form>

      {status && <div class={`status-message ${status.type}`}>{status.message}</div>}
    </section>
  );
}
