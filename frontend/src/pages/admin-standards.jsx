import { useState, useEffect, useCallback, useRef } from 'preact/hooks';
import { useI18n } from '../i18n-context.jsx';
import { useAuth } from '../auth.jsx';
import { DeleteButton } from '../components/action-buttons.jsx';
import {
  getAdminStandards,
  uploadAdminStandard,
  updateAdminStandardMetadata,
  deleteAdminStandard,
  syncAdminStandards,
  getAdminStandardsSyncStatus,
} from '../api.js';

const SOURCE_TYPES = [
  'prudential_standard',
  'prudential_guidance',
  'regulatory_commentary',
  'industry_framework',
  'legislation',
];

const JURISDICTIONS = ['AU', 'EU', 'US', 'UK', 'international'];

const INDUSTRIES = ['financial_services', 'general', 'automotive'];

function formatBytes(bytes) {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    });
  } catch {
    return iso;
  }
}

/** Translate a controlled value, falling back to title-cased raw value. */
function translateValue(t, prefix, value) {
  if (!value) return '—';
  const key = `${prefix}.${value}`;
  const translated = t(key);
  return translated !== key ? translated : value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function AdminStandardsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.groups?.includes('admins');
  // Viewers may read the standards corpus; write controls remain gated on readOnly.
  const canView = isAdmin || user?.readOnly;

  // Standards list
  const [standards, setStandards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Selection
  const [selected, setSelected] = useState(new Set());
  const [deleting, setDeleting] = useState(false);

  // Upload form
  const [showUpload, setShowUpload] = useState(false);
  const [uploadForm, setUploadForm] = useState({
    standard_id: '', source_type: '', jurisdiction: '', industry: '', file: null,
  });
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  // Inline edit — track by S3 key (unique) rather than standard_id (may have duplicates)
  const [editingKey, setEditingKey] = useState(null);
  const [editStandardId, setEditStandardId] = useState(null);
  const [editForm, setEditForm] = useState({ source_type: '', jurisdiction: '', industry: '' });
  const [savingEdit, setSavingEdit] = useState(false);

  // Sync
  const [syncing, setSyncing] = useState(false);
  const [pendingChanges, _setPendingChanges] = useState(
    () => sessionStorage.getItem('std_pending_sync') === '1',
  );
  const syncPollRef = useRef(null);

  /** Update pending-changes flag in both state and sessionStorage. */
  function setPendingChanges(value) {
    _setPendingChanges(value);
    if (value) sessionStorage.setItem('std_pending_sync', '1');
    else sessionStorage.removeItem('std_pending_sync');
  }

  // Status messages
  const [statusMsg, setStatusMsg] = useState('');
  const [statusType, setStatusType] = useState('');

  const showStatus = useCallback((msg, type = 'success') => {
    setStatusMsg(msg);
    setStatusType(type);
  }, []);

  // Load standards
  const loadStandards = useCallback(() => {
    getAdminStandards()
      .then((d) => {
        setStandards(d.standards || []);
        setSelected(new Set());
        setError('');
      })
      .catch((e) => {
        const msg = e.status === 503
          ? t('admin.standards.notConfigured')
          : t('admin.standards.loadFailed', { message: e.message });
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [t]);

  useEffect(() => {
    if (!canView) { setLoading(false); return; }
    loadStandards();
  }, [canView, loadStandards]);

  useEffect(() => {
    return () => { if (syncPollRef.current) clearInterval(syncPollRef.current); };
  }, []);

  // --- Selection ---
  function toggleSelect(standardId, e) {
    e.stopPropagation();
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(standardId)) next.delete(standardId); else next.add(standardId);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selected.size === standards.length) setSelected(new Set());
    else setSelected(new Set(standards.map((s) => s.standard_id)));
  }

  // --- Delete ---
  async function handleDeleteSelected() {
    if (selected.size === 0) return;
    if (!confirm(t('admin.standards.bulkDeleteConfirm', { count: selected.size }))) return;
    setDeleting(true);
    setStatusMsg('');
    try {
      await Promise.all([...selected].map((id) => deleteAdminStandard(id)));
      showStatus(t('admin.standards.deleteSuccess', { count: selected.size }));
      setPendingChanges(true);
      loadStandards();
    } catch (e) {
      showStatus(t('admin.standards.deleteFailed', { message: e.message }), 'error');
    } finally {
      setDeleting(false);
    }
  }

  // --- Upload ---
  function handleFileChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const id = file.name.replace(/\.md$/i, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    setUploadForm((prev) => ({ ...prev, file, standard_id: prev.standard_id || id }));
  }

  async function handleUpload() {
    const { standard_id, source_type, jurisdiction, industry, file } = uploadForm;
    if (!standard_id || !source_type || !file) return;

    // Derive MIME type from file extension
    const ext = file.name.split('.').pop()?.toLowerCase();
    const mimeTypes = {
      md: 'text/markdown', txt: 'text/plain', html: 'text/html',
      pdf: 'application/pdf', doc: 'application/msword',
      docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      csv: 'text/csv',
    };
    const contentType = mimeTypes[ext] || 'application/octet-stream';

    setUploading(true);
    setStatusMsg('');
    try {
      const result = await uploadAdminStandard(standard_id, source_type, file.name, jurisdiction, industry, contentType);
      const uploadRes = await fetch(result.upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': contentType },
      });
      if (!uploadRes.ok) throw new Error(`S3 upload failed (${uploadRes.status})`);

      showStatus(t('admin.standards.uploadSuccess'));
      setPendingChanges(true);
      setShowUpload(false);
      setUploadForm({ standard_id: '', source_type: '', jurisdiction: '', industry: '', file: null });
      if (fileInputRef.current) fileInputRef.current.value = '';
      loadStandards();
    } catch (e) {
      showStatus(t('admin.standards.uploadFailed', { message: e.message }), 'error');
    } finally {
      setUploading(false);
    }
  }

  // --- Edit metadata ---
  function startEdit(s) {
    setEditingKey(s.key);
    setEditStandardId(s.standard_id);
    setEditForm({
      source_type: s.source_type || '',
      jurisdiction: s.jurisdiction || '',
      industry: s.industry || '',
    });
    setStatusMsg('');
  }

  async function handleSaveEdit() {
    setSavingEdit(true);
    setStatusMsg('');
    try {
      await updateAdminStandardMetadata(editStandardId, editForm.source_type, editForm.jurisdiction, editForm.industry);
      showStatus(t('admin.standards.metadataUpdated'));
      setPendingChanges(true);
      setEditingKey(null);
      loadStandards();
    } catch (e) {
      showStatus(t('admin.standards.metadataUpdateFailed', { message: e.message }), 'error');
    } finally {
      setSavingEdit(false);
    }
  }

  // --- Sync ---
  async function handleSync() {
    setSyncing(true);
    setStatusMsg('');
    try {
      await syncAdminStandards();
      showStatus(t('admin.standards.syncStarted'), 'info');
      pollSyncStatus();
    } catch (e) {
      setSyncing(false);
      const msg = e.status === 503
        ? t('admin.standards.syncNotConfigured')
        : t('admin.standards.syncError', { message: e.message });
      showStatus(msg, 'error');
    }
  }

  function pollSyncStatus() {
    if (syncPollRef.current) clearInterval(syncPollRef.current);
    syncPollRef.current = setInterval(async () => {
      try {
        const status = await getAdminStandardsSyncStatus();
        if (status.status === 'COMPLETE') {
          clearInterval(syncPollRef.current);
          syncPollRef.current = null;
          setSyncing(false);
          setPendingChanges(false);
          const s = status.statistics || {};
          showStatus(t('admin.standards.syncComplete', {
            scanned: s.documents_scanned ?? 0,
            indexed: s.documents_indexed ?? 0,
            failed: s.documents_failed ?? 0,
          }));
          loadStandards();
        } else if (status.status === 'FAILED') {
          clearInterval(syncPollRef.current);
          syncPollRef.current = null;
          setSyncing(false);
          showStatus(t('admin.standards.syncFailed'), 'error');
        }
      } catch {
        clearInterval(syncPollRef.current);
        syncPollRef.current = null;
        setSyncing(false);
      }
    }, 3000);
  }

  // --- Render ---
  if (loading) return <div class="page-section"><p>{t('admin.standards.loading')}</p></div>;
  if (!canView) return <div class="page-section"><p class="empty-state">{t('admin.noAccess')}</p></div>;

  return (
    <section class="page-section">
      <div class="page-header">
        <h2>{t('admin.standards.title')}</h2>
        <div class="page-actions">
          {selected.size > 0 && (
            <DeleteButton
              onClick={handleDeleteSelected}
              deleting={deleting}
              small={false}
              label={t('admin.standards.deleteSelected', { count: selected.size })}
              disabled={user.readOnly}
            />
          )}
          <button
            class={`btn ${pendingChanges ? 'btn-warning' : 'btn-secondary'}`}
            onClick={handleSync}
            disabled={syncing || user.readOnly}
          >
            {syncing ? t('admin.standards.syncing') : t('admin.standards.syncNow')}
          </button>
          <button class="btn btn-primary" onClick={() => setShowUpload(!showUpload)} disabled={user.readOnly}>
            {showUpload ? t('common.cancel') : t('admin.standards.upload')}
          </button>
        </div>
      </div>

      {statusMsg && (
        <div class={`status-message ${statusType === 'error' ? 'error' : statusType === 'info' ? '' : 'success'}`}
          style="margin-bottom:1rem">
          {statusMsg}
        </div>
      )}

      {/* Upload form */}
      {showUpload && (
        <div class="create-form" style="margin-bottom:1rem">
          <div class="form-group">
            <label>{t('admin.standards.standardId')}</label>
            <input
              type="text"
              placeholder={t('admin.standards.standardIdPlaceholder')}
              value={uploadForm.standard_id}
              onInput={(e) => setUploadForm({ ...uploadForm, standard_id: e.target.value })}
            />
            <p class="form-hint">{t('admin.standards.standardIdHint')}</p>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.75rem">
            <div class="form-group">
              <label>{t('admin.standards.sourceType')}</label>
              <select
                class="filter-select"
                value={uploadForm.source_type}
                onChange={(e) => setUploadForm({ ...uploadForm, source_type: e.target.value })}
              >
                <option value="">{t('admin.standards.sourceTypePlaceholder')}</option>
                {SOURCE_TYPES.map((st) => (
                  <option key={st} value={st}>{t(`admin.standards.sourceTypes.${st}`)}</option>
                ))}
              </select>
            </div>
            <div class="form-group">
              <label>{t('admin.standards.jurisdiction')}</label>
              <select
                class="filter-select"
                value={uploadForm.jurisdiction}
                onChange={(e) => setUploadForm({ ...uploadForm, jurisdiction: e.target.value })}
              >
                <option value="">{t('admin.standards.jurisdictionPlaceholder')}</option>
                {JURISDICTIONS.map((j) => (
                  <option key={j} value={j}>{t(`admin.standards.jurisdictions.${j}`)}</option>
                ))}
              </select>
            </div>
            <div class="form-group">
              <label>{t('admin.standards.industry')}</label>
              <select
                class="filter-select"
                value={uploadForm.industry}
                onChange={(e) => setUploadForm({ ...uploadForm, industry: e.target.value })}
              >
                <option value="">{t('admin.standards.industryPlaceholder')}</option>
                {INDUSTRIES.map((i) => (
                  <option key={i} value={i}>{t(`admin.standards.industries.${i}`)}</option>
                ))}
              </select>
            </div>
          </div>
          <div class="form-group">
            <label>{t('admin.standards.file')}</label>
            <div
              class="file-dropzone"
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) handleFileChange({ target: { files: [f] } }); }}
              role="button"
              tabIndex={0}
              aria-label={t('admin.standards.file')}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".md,.pdf,.txt,.html,.doc,.docx,.csv"
                onChange={handleFileChange}
                style="display:none"
              />
              {uploadForm.file ? (
                <div class="file-dropzone-content">
                  <span class="file-dropzone-icon">📝</span>
                  <span>{uploadForm.file.name}</span>
                  <span class="file-dropzone-hint">{formatBytes(uploadForm.file.size)}</span>
                </div>
              ) : (
                <div class="file-dropzone-content">
                  <span class="file-dropzone-icon">📎</span>
                  <span>{t('admin.standards.fileDropzone')}</span>
                  <span class="file-dropzone-hint">{t('admin.standards.fileHint')}</span>
                </div>
              )}
            </div>
          </div>
          <button
            class="btn btn-primary"
            onClick={handleUpload}
            disabled={uploading || !uploadForm.standard_id || !uploadForm.source_type || !uploadForm.file || user.readOnly}
          >
            {uploading ? t('admin.standards.uploading') : t('admin.standards.upload')}
          </button>
        </div>
      )}

      {/* Error state */}
      {error && <div class="status-message error" style="margin-bottom:1rem">{error}</div>}

      {/* Empty state */}
      {!error && standards.length === 0 && (
        <div class="empty-state"><p>{t('admin.standards.empty')}</p></div>
      )}

      {/* Standards table */}
      {!error && standards.length > 0 && (
        <>
          <p style="margin-bottom:0.75rem;color:var(--text-secondary)">
            {t('admin.standards.count', { count: standards.length })}
          </p>
          <div class="projects-table">
            <div class="std-header">
              <div class="std-cell std-sel">
                <input
                  type="checkbox"
                  checked={selected.size === standards.length && standards.length > 0}
                  onChange={toggleSelectAll}
                  aria-label={t('admin.standards.selectAll', { count: standards.length })}
                />
              </div>
              <div class="std-cell std-name">{t('admin.standards.standard')}</div>
              <div class="std-cell std-type">{t('admin.standards.type')}</div>
              <div class="std-cell std-jurisdiction">{t('admin.standards.jurisdiction')}</div>
              <div class="std-cell std-industry">{t('admin.standards.industry')}</div>
              <div class="std-cell std-date">{t('admin.standards.lastModified')}</div>
              <div class="std-cell std-actions"></div>
            </div>

            {standards.map((s) => {
              const isSelected = selected.has(s.standard_id);
              const isEditing = editingKey === s.key;
              return (
                <div key={s.key} class={`std-row ${isSelected ? 'selected' : ''} ${isEditing ? 'admin-row-editing' : ''}`}>
                  <div class="std-cell std-sel" role="checkbox" aria-checked={isSelected} tabIndex={0}
                    onClick={(e) => toggleSelect(s.standard_id, e)}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && toggleSelect(s.standard_id, e)}>
                    <input type="checkbox" checked={isSelected} tabIndex={-1} />
                  </div>
                  <div class="std-cell std-name" title={s.key}>{s.standard_id}</div>
                  <div class="std-cell std-type">
                    {isEditing ? (
                      <select class="std-inline-select" value={editForm.source_type}
                        onChange={(e) => setEditForm({ ...editForm, source_type: e.target.value })}>
                        <option value="">{t('admin.standards.sourceTypePlaceholder')}</option>
                        {SOURCE_TYPES.map((st) => (
                          <option key={st} value={st}>{t(`admin.standards.sourceTypes.${st}`)}</option>
                        ))}
                      </select>
                    ) : translateValue(t, 'admin.standards.sourceTypes', s.source_type)}
                  </div>
                  <div class="std-cell std-jurisdiction">
                    {isEditing ? (
                      <select class="std-inline-select" value={editForm.jurisdiction}
                        onChange={(e) => setEditForm({ ...editForm, jurisdiction: e.target.value })}>
                        <option value="">{t('admin.standards.jurisdictionPlaceholder')}</option>
                        {JURISDICTIONS.map((j) => (
                          <option key={j} value={j}>{t(`admin.standards.jurisdictions.${j}`)}</option>
                        ))}
                      </select>
                    ) : translateValue(t, 'admin.standards.jurisdictions', s.jurisdiction)}
                  </div>
                  <div class="std-cell std-industry">
                    {isEditing ? (
                      <select class="std-inline-select" value={editForm.industry}
                        onChange={(e) => setEditForm({ ...editForm, industry: e.target.value })}>
                        <option value="">{t('admin.standards.industryPlaceholder')}</option>
                        {INDUSTRIES.map((i) => (
                          <option key={i} value={i}>{t(`admin.standards.industries.${i}`)}</option>
                        ))}
                      </select>
                    ) : translateValue(t, 'admin.standards.industries', s.industry)}
                  </div>
                  <div class="std-cell std-date">{formatDate(s.last_modified)}</div>
                  <div class="std-cell std-actions">
                    {isEditing ? (
                      <div class="std-actions-edit">
                        <button class="btn btn-primary btn-small" onClick={handleSaveEdit}
                          disabled={savingEdit || !editForm.source_type || user.readOnly}>
                          {savingEdit ? t('common.saving') : t('common.save')}
                        </button>
                        <button class="btn btn-secondary btn-small" onClick={() => setEditingKey(null)}>
                          {t('common.cancel')}
                        </button>
                      </div>
                    ) : (
                      <button
                        class="btn btn-secondary btn-small"
                        onClick={() => startEdit(s)}
                      >
                        {t('common.edit')}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
