import { useState, useEffect } from 'preact/hooks';
import { getProject } from '../api.js';
import { useI18n } from '../i18n-context.jsx';

const LIKELIHOOD_LEVELS = ['almost_certain', 'likely', 'possible', 'unlikely', 'rare'];
const CONSEQUENCE_LEVELS = ['insignificant', 'minor', 'moderate', 'major', 'catastrophic'];

const SEVERITY_MATRIX = {
  'almost_certain:catastrophic': 'critical', 'almost_certain:major': 'critical',
  'almost_certain:moderate': 'high', 'almost_certain:minor': 'medium', 'almost_certain:insignificant': 'medium',
  'likely:catastrophic': 'critical', 'likely:major': 'high',
  'likely:moderate': 'high', 'likely:minor': 'medium', 'likely:insignificant': 'low',
  'possible:catastrophic': 'high', 'possible:major': 'high',
  'possible:moderate': 'medium', 'possible:minor': 'low', 'possible:insignificant': 'low',
  'unlikely:catastrophic': 'high', 'unlikely:major': 'medium',
  'unlikely:moderate': 'medium', 'unlikely:minor': 'low', 'unlikely:insignificant': 'low',
  'rare:catastrophic': 'medium', 'rare:major': 'medium',
  'rare:moderate': 'low', 'rare:minor': 'low', 'rare:insignificant': 'low',
};

const CELL_COLORS = {
  critical: 'rgba(136, 14, 79, 0.35)',
  high: 'rgba(220, 53, 69, 0.25)',
  medium: 'rgba(255, 193, 7, 0.2)',
  low: 'rgba(40, 167, 69, 0.15)',
};

const SEVERITY_TEXT_COLORS = {
  critical: '#e040fb',
  high: 'var(--danger-color)',
  medium: 'var(--warning-color)',
  low: 'var(--success-color)',
};

/**
 * Extract risk findings from a completed project's review result.
 *
 * @param {object} project - Project object with review.result
 * @returns {Array} Risk findings with likelihood and consequence fields
 * @throws {SyntaxError} If review.result is a malformed JSON string
 */
function parseRiskFindings(project) {
  if (project.status !== 'completed' || !project.review?.result) return [];
  const result =
    typeof project.review.result === 'string'
      ? JSON.parse(project.review.result)
      : project.review.result;
  const risk = (result.reviews || {}).risk;
  if (!risk) return [];
  return (risk.findings || []).filter((f) => f.likelihood && f.consequence);
}

function cellKey(lk, cq) { return `${lk}:${cq}`; }

export function RiskHeatmapPage({ projectId }) {
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [findings, setFindings] = useState([]);
  const [error, setError] = useState(null);
  const { t } = useI18n();

  useEffect(() => {
    getProject(projectId)
      .then((data) => {
        try {
          setFindings(parseRiskFindings(data));
        } catch (e) {
          setError(`Failed to parse review data: ${e.message}`);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [projectId]);

  // Group findings by cell
  const cellFindings = {};
  findings.forEach((f) => {
    const key = cellKey(f.likelihood, f.consequence);
    if (!cellFindings[key]) cellFindings[key] = [];
    cellFindings[key].push(f);
  });

  if (loading) return <p class="status-message loading">{t('common.loading')}</p>;
  if (error) return <p class="status-message error">{error}</p>;

  return (
    <section class="page-section">
      <div class="page-header">
        <h2>{t('heatmap.title')}</h2>
        <a href={`/projects/${projectId}`} class="btn btn-secondary btn-small">
          {t('project.backToProject')}
        </a>
      </div>

      {findings.length === 0 ? (
        <p style="color: var(--text-secondary); text-align: center; padding: 2rem;">
          {t('heatmap.noFindings')}
        </p>
      ) : (
        <div class="risk-matrix-layout">
          <div class="risk-matrix-left">
            <div class="risk-matrix-container">
              <div class="risk-matrix-ylabel">Likelihood →</div>
              <table class="risk-matrix-table" role="grid" aria-label="Risk matrix">
                <thead>
                  <tr>
                    <th class="risk-matrix-corner" />
                    {CONSEQUENCE_LEVELS.map((cq) => (
                      <th key={cq} class="risk-matrix-col-header">{cq.replace('_', ' ')}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...LIKELIHOOD_LEVELS].map((lk) => (
                    <tr key={lk}>
                      <th class="risk-matrix-row-header">{lk.replace('_', ' ')}</th>
                      {CONSEQUENCE_LEVELS.map((cq) => {
                        const key = cellKey(lk, cq);
                        const sev = SEVERITY_MATRIX[key] || 'low';
                        const items = cellFindings[key] || [];
                        const isSelected = selected && selected.key === key;
                        return (
                          <td
                            key={key}
                            class={`risk-matrix-cell ${sev} ${items.length > 0 ? 'has-findings' : ''} ${isSelected ? 'selected' : ''}`}
                            style={{ background: CELL_COLORS[sev] }}
                            onClick={() => items.length > 0 && setSelected(isSelected ? null : { key, items, sev })}
                            role="gridcell"
                            tabIndex={items.length > 0 ? 0 : -1}
                            aria-label={`${lk} likelihood, ${cq} consequence: ${sev} severity, ${items.length} findings`}
                          >
                            {items.length > 0 && (
                              <span class="risk-matrix-count" style={{ color: SEVERITY_TEXT_COLORS[sev] }}>
                                {items.length}
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div class="risk-matrix-xlabel">Consequence →</div>
            </div>

            <div class="risk-matrix-legend">
              {['critical', 'high', 'medium', 'low'].map((sev) => (
                <div key={sev} class="legend-item">
                  <span class="legend-dot" style={{ background: CELL_COLORS[sev], border: `1px solid ${SEVERITY_TEXT_COLORS[sev]}` }} />
                  <span>{sev}</span>
                </div>
              ))}
              <span class="heatmap-count">{t('heatmap.count', { count: findings.length })}</span>
            </div>
          </div>

          {selected ? (
            <div class="risk-matrix-detail">
              <h4>
                {selected.sev.toUpperCase()} — {selected.items.length} finding{selected.items.length !== 1 ? 's' : ''}
              </h4>
              {selected.items.map((f) => (
                <div key={f.id} class="risk-matrix-finding">
                  <div class="risk-matrix-finding-header">
                    <span class="finding-id">{f.id}</span>
                    <span class={`severity-badge ${f.severity}`}>{f.severity}</span>
                  </div>
                  <p class="risk-matrix-finding-title">{f.title}</p>
                  {f.risk_treatment && (
                    <span class={`finding-tag treatment ${f.risk_treatment}`}>{f.risk_treatment}</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div class="risk-matrix-detail risk-matrix-detail--empty">
              <p class="empty-panel-text">{t('heatmap.selectCell')}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
