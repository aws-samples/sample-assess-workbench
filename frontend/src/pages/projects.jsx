import { useState, useEffect, useMemo } from 'preact/hooks';
import { route } from 'preact-router';
import { listProjects, deleteProject } from '../api.js';
import { DeleteButton } from '../components/action-buttons.jsx';
import { useI18n } from '../i18n-context.jsx';
import { useAuth } from '../auth.jsx';

function projectRoute(p) {
  if (p.status === 'in_progress') {
    return p.latest_review_id
      ? `/projects/${p.project_id}/live/${p.latest_review_id}`
      : `/projects/${p.project_id}/live`;
  }
  return `/projects/${p.project_id}`;
}

const STATUS_COLORS = {
  completed: 'success',
  in_progress: 'warning',
  pending: 'secondary',
  failed: 'danger',
};


function timeAgo(dateStr) {
  if (!dateStr) return '—';
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

function SortArrow({ column, sortBy, sortDir }) {
  if (sortBy !== column) return <span class="sort-arrow muted">↕</span>;
  return <span class="sort-arrow active">{sortDir === 'asc' ? '↑' : '↓'}</span>;
}

export function ProjectsPage() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(new Set());
  const [deleting, setDeleting] = useState(false);
  const [sortBy, setSortBy] = useState('updated_at');
  const [sortDir, setSortDir] = useState('desc');
  const { t } = useI18n();
  const { user } = useAuth();
  // Read-only (viewer/demo) users can't delete, so hide selection + bulk delete.
  const canSelect = !user.readOnly;

  useEffect(() => { loadProjects(); }, [filter]);

  async function loadProjects() {
    setLoading(true);
    setError(null);
    try {
      const data = await listProjects(filter || undefined);
      setProjects(data.projects || []);
      setSelected(new Set());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const sortedProjects = useMemo(() => {
    let list = projects;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(p =>
        p.name.toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q) ||
        (p.created_by_email || '').toLowerCase().includes(q)
      );
    }
    return [...list].sort((a, b) => {
      let cmp = 0;
      switch (sortBy) {
        case 'name':
          cmp = a.name.localeCompare(b.name);
          break;
        case 'owner':
          cmp = (a.created_by_email || '').localeCompare(b.created_by_email || '');
          break;
        case 'created_at':
        case 'updated_at':
          cmp = new Date(a[sortBy] || 0) - new Date(b[sortBy] || 0);
          break;
        default:
          cmp = 0;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [projects, search, sortBy, sortDir]);

  function handleSort(col) {
    if (sortBy === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(col);
      setSortDir(col === 'name' ? 'asc' : 'desc');
    }
  }

  function toggleSelect(projectId, e) {
    e.stopPropagation();
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(projectId)) next.delete(projectId); else next.add(projectId);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selected.size === sortedProjects.length) setSelected(new Set());
    else setSelected(new Set(sortedProjects.map(p => p.project_id)));
  }

  async function handleDeleteSelected() {
    if (selected.size === 0) return;
    if (!confirm(t('project.delete.bulkConfirm', { count: selected.size }))) return;
    setDeleting(true);
    setError(null);
    try {
      await Promise.all([...selected].map(id => deleteProject(id)));
      await loadProjects();
    } catch (e) {
      setError(t('project.deleteFailed', { message: e.message }));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section class="page-section">
      <div class="page-header">
        <h2>📋 {t('nav.projects')}</h2>
        <div class="page-actions">
          {canSelect && selected.size > 0 && (
            <DeleteButton onClick={handleDeleteSelected} deleting={deleting} small={false}
              label={t('project.deleteSelected', { count: selected.size })} />
          )}
          <input
            type="text"
            class="search-input"
            placeholder={t('project.searchPlaceholder')}
            value={search}
            onInput={e => setSearch(e.target.value)}
            aria-label="Search projects"
          />
          <select class="filter-select" value={filter}
            onChange={e => setFilter(e.target.value)} aria-label="Filter by status">
            <option value="">{t('project.filterAll')}</option>
            <option value="pending">{t('project.status.pending')}</option>
            <option value="in_progress">{t('project.status.in_progress')}</option>
            <option value="completed">{t('project.status.completed')}</option>
            <option value="failed">{t('project.status.failed')}</option>
          </select>
          <button class="btn btn-primary" onClick={() => route('/create')}>
            {t('project.newProject')}
          </button>
        </div>
      </div>

      {loading && <p class="status-message loading">{t('project.loadingProjects')}</p>}
      {error && <p class="status-message error">{error}</p>}

      {!loading && projects.length === 0 && (
        <div class="empty-state"><p>{t('project.noProjects')}</p></div>
      )}

      {sortedProjects.length > 0 && (
        <div class={`projects-table${canSelect ? '' : ' no-sel'}`}>
          {/* Header row */}
          <div class="ptr-header">
            {canSelect && (
              <div class="ptr-cell ptr-sel">
                <input type="checkbox" checked={selected.size === sortedProjects.length && sortedProjects.length > 0}
                  onChange={toggleSelectAll} aria-label="Select all" />
              </div>
            )}
            <div class={`ptr-cell ptr-name ptr-sortable ${sortBy === 'name' ? 'sort-active' : ''}`} role="button" tabIndex={0} onClick={() => handleSort('name')} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleSort('name')}>
              {t('project.table.project')} <SortArrow column="name" sortBy={sortBy} sortDir={sortDir} />
            </div>
            <div class="ptr-cell ptr-status">
              {t('project.table.status')}
            </div>
            <div class={`ptr-cell ptr-author ptr-sortable ${sortBy === 'owner' ? 'sort-active' : ''}`} role="button" tabIndex={0} onClick={() => handleSort('owner')} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleSort('owner')}>
              {t('project.table.owner')} <SortArrow column="owner" sortBy={sortBy} sortDir={sortDir} />
            </div>
            <div class={`ptr-cell ptr-date ptr-sortable ${sortBy === 'created_at' ? 'sort-active' : ''}`} role="button" tabIndex={0} onClick={() => handleSort('created_at')} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleSort('created_at')}>
              {t('project.table.created')} <SortArrow column="created_at" sortBy={sortBy} sortDir={sortDir} />
            </div>
            <div class={`ptr-cell ptr-date ptr-sortable ${sortBy === 'updated_at' ? 'sort-active' : ''}`} role="button" tabIndex={0} onClick={() => handleSort('updated_at')} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && handleSort('updated_at')}>
              {t('project.table.updated')} <SortArrow column="updated_at" sortBy={sortBy} sortDir={sortDir} />
            </div>
          </div>

          {/* Data rows */}
          {sortedProjects.map(p => {
            const isSelected = selected.has(p.project_id);
            return (
              <div key={p.project_id}
                class={`ptr-row ${isSelected ? 'selected' : ''}`}
                onClick={() => route(projectRoute(p))}
                role="link" tabIndex={0}
                onKeyDown={e => e.key === 'Enter' && route(projectRoute(p))}>
                {canSelect && (
                  <div class="ptr-cell ptr-sel" role="checkbox" aria-checked={isSelected} tabIndex={0} onClick={e => toggleSelect(p.project_id, e)} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && toggleSelect(p.project_id, e)}>
                    <input type="checkbox" checked={isSelected} tabIndex={-1} />
                  </div>
                )}
                <div class="ptr-cell ptr-name">
                  <span class="ptr-project-name">{p.name}</span>
                  {p.description && <span class="ptr-project-desc">{p.description}</span>}
                </div>
                <div class="ptr-cell ptr-status">
                  <span class={`badge badge-sm ${STATUS_COLORS[p.status] || ''}`}>
                    {t(`project.status.${p.status}`)}
                  </span>
                </div>
                <div class="ptr-cell ptr-author" title={p.created_by_email}>
                  {p.created_by_email?.split('@')[0] || '—'}
                </div>
                <div class="ptr-cell ptr-date">{timeAgo(p.created_at)}</div>
                <div class="ptr-cell ptr-date">{timeAgo(p.updated_at)}</div>
              </div>
            );
          })}
        </div>
      )}

      {!loading && projects.length > 0 && sortedProjects.length === 0 && (
        <div class="empty-state"><p>{t('project.noMatch', { search })}</p></div>
      )}
    </section>
  );
}
