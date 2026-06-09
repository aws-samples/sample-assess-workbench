import { useHealthCheck } from '../hooks/useHealthCheck.js';
import { useI18n } from '../i18n-context.jsx';

/**
 * Full-width banner shown when the backend API is unreachable.
 * Renders nothing when healthy — zero visual footprint.
 */
export function HealthBanner() {
  const { healthy, checking, retryNow } = useHealthCheck();
  const { t } = useI18n();

  if (healthy) return null;

  return (
    <div class="health-banner" role="alert">
      <span class="health-banner-icon">⚠</span>
      <span class="health-banner-text">{t('health.unreachable')}</span>
      <button
        class="health-banner-retry"
        onClick={retryNow}
        disabled={checking}
      >
        {checking ? t('health.checking') : t('health.retry')}
      </button>
    </div>
  );
}
