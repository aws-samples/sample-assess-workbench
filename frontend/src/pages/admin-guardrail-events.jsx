import { useState, useEffect, useCallback } from 'preact/hooks';
import { useI18n } from '../i18n-context.jsx';
import { useAuth } from '../auth.jsx';
import { getGuardrailEvents } from '../api.js';

/** Format an ISO timestamp for display. */
function formatTimestamp(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return iso;
  }
}

/** Compute an ISO date string N days ago from now. */
function daysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString();
}

const RANGE_OPTIONS = [
  { key: 'last1', days: 1 },
  { key: 'last7', days: 7 },
  { key: 'last30', days: 30 },
];

export function AdminGuardrailEventsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const isAdmin = user?.groups?.includes('admins');
  // Read-only page; viewers may also read it (exposes user emails — acceptable
  // for the trusted viewer role, see backend can_read_admin_views).
  const canView = isAdmin || user?.readOnly;

  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [configured, setConfigured] = useState(true);
  const [projectFilter, setProjectFilter] = useState('');
  const [rangeDays, setRangeDays] = useState(30);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const startDate = daysAgo(rangeDays);
      const data = await getGuardrailEvents(
        projectFilter || undefined,
        startDate,
        undefined,
        200,
      );
      setEvents(data.events || []);
      setConfigured(data.configured !== false);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [rangeDays, projectFilter]);

  useEffect(() => {
    if (!canView) { setLoading(false); return; }
    fetchEvents();
  }, [canView, fetchEvents]);

  if (!canView) {
    return (
      <div class="page-section">
        <p class="empty-state">{t('admin.noAccess')}</p>
      </div>
    );
  }

  return (
    <div class="page-section">
      <div class="page-header">
        <h2>{t('admin.guardrails.title')}</h2>
      </div>

      {/* Filters */}
      <div class="admin-filters" style="display:flex;gap:0.75rem;align-items:center;margin-bottom:1rem;flex-wrap:wrap">
        <input
          type="text"
          class="admin-input-sm"
          placeholder={t('admin.guardrails.filterProject')}
          value={projectFilter}
          onInput={(e) => setProjectFilter(e.target.value)}
          style="width:220px"
        />
        <div style="display:flex;gap:0.25rem">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              class={`btn btn-small ${rangeDays === opt.days ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setRangeDays(opt.days)}
            >
              {t(`admin.guardrails.${opt.key}`)}
            </button>
          ))}
        </div>
        <button class="btn btn-secondary btn-small" onClick={fetchEvents} disabled={loading}>
          {t('admin.guardrails.refresh')}
        </button>
        {!loading && events.length > 0 && (
          <span class="text-muted" style="margin-left:auto">
            {t('admin.guardrails.count', { count: events.length })}
          </span>
        )}
      </div>

      {/* Content */}
      {loading && <p>{t('admin.guardrails.loading')}</p>}
      {error && <div class="status-message error">{t('admin.guardrails.loadFailed', { message: error })}</div>}
      {!loading && !error && !configured && (
        <p class="empty-state">{t('admin.guardrails.notConfigured')}</p>
      )}
      {!loading && !error && configured && events.length === 0 && (
        <p class="empty-state">{t('admin.guardrails.empty')}</p>
      )}
      {!loading && !error && configured && events.length > 0 && (
        <table class="admin-table">
          <thead>
            <tr>
              <th>{t('admin.guardrails.timestamp')}</th>
              <th>{t('admin.guardrails.project')}</th>
              <th>{t('admin.guardrails.agent')}</th>
              <th>{t('admin.guardrails.action')}</th>
              <th>{t('admin.guardrails.user')}</th>
            </tr>
          </thead>
          <tbody>
            {events.map((evt, i) => (
              <tr key={i}>
                <td style="white-space:nowrap">{formatTimestamp(evt.timestamp)}</td>
                <td>
                  {evt.project_id ? (
                    <a href={`/projects/${evt.project_id}`} style="color: var(--color-info-text)">{evt.project_id.slice(0, 8)}…</a>
                  ) : '—'}
                </td>
                <td>{evt.agent_type || '—'}</td>
                <td>
                  <span class="badge danger">{evt.action_taken || '—'}</span>
                </td>
                <td>{evt.user_email || evt.user_sub || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
