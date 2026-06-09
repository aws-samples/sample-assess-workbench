import { useState } from 'preact/hooks';
import { useI18n } from '../i18n-context.jsx';
import { renderMarkdown } from '../markdown.js';

/**
 * Schema-driven badge renderer. Reads `display` and `color` hints from
 * the field definitions in the agent registry and renders badges/tags
 * in the finding's top tags row.
 *
 * Handles display hints: badge, tag_list. Skips: detail_only, hidden, section.
 */
function DynamicBadges({ finding, fieldDefinitions }) {
  if (!fieldDefinitions) return null;
  return (
    <>
      {Object.entries(fieldDefinitions).map(([fieldName, fieldDef]) => {
        const value = finding[fieldName];
        if (!value || (Array.isArray(value) && value.length === 0)) return null;
        if (!fieldDef.display || fieldDef.display === 'detail_only' || fieldDef.display === 'hidden' || fieldDef.display === 'section') return null;

        const colorClass = fieldDef.color ? `tag-${fieldDef.color}` : fieldName;

        if (fieldDef.display === 'tag_list' && Array.isArray(value)) {
          return value.map((item) => (
            <span key={`${fieldName}-${item}`} class={`finding-tag ${colorClass}`}>{item}</span>
          ));
        }

        if (fieldDef.display === 'badge') {
          return <span key={fieldName} class={`finding-tag ${colorClass}`}>{String(value).replace(/_/g, ' ')}</span>;
        }

        return null;
      })}
    </>
  );
}

/**
 * Schema-driven section renderer. Renders fields with display: section
 * as their own container below the description/recommendation.
 */
function DynamicSections({ finding, fieldDefinitions }) {
  if (!fieldDefinitions) return null;
  return (
    <>
      {Object.entries(fieldDefinitions).map(([fieldName, fieldDef]) => {
        if (fieldDef.display !== 'section') return null;
        const value = finding[fieldName];
        if (!value || (Array.isArray(value) && value.length === 0)) return null;

        const items = Array.isArray(value) ? value : [value];
        const colorClass = fieldDef.color ? `tag-${fieldDef.color}` : fieldName;
        return (
          <div key={fieldName} class={`finding-${fieldName}`}>
            {items.map((item, i) => (
              <span key={i} class={`finding-tag ${colorClass}`}>{item}</span>
            ))}
          </div>
        );
      })}
    </>
  );
}

function FeedbackButtons({ findingId, currentValue, onFeedback }) {
  const [submitting, setSubmitting] = useState(false);

  async function handleClick(value, e) {
    e.stopPropagation();
    if (submitting) return;
    // Toggle off if clicking the already-selected value
    const newValue = currentValue === value ? null : value;
    setSubmitting(true);
    try {
      await onFeedback(findingId, newValue);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <span class="feedback-buttons" role="group" aria-label="Finding feedback">
      <button
        class={`feedback-btn ${currentValue === 'up' ? 'active' : ''}`}
        onClick={(e) => handleClick('up', e)}
        onKeyDown={(e) => e.key === 'Enter' && handleClick('up', e)}
        disabled={submitting}
        aria-label="Thumbs up"
        aria-pressed={currentValue === 'up'}
        title="Helpful finding"
      >
        👍
      </button>
      <button
        class={`feedback-btn ${currentValue === 'down' ? 'active' : ''}`}
        onClick={(e) => handleClick('down', e)}
        onKeyDown={(e) => e.key === 'Enter' && handleClick('down', e)}
        disabled={submitting}
        aria-label="Thumbs down"
        aria-pressed={currentValue === 'down'}
        title="Not helpful"
      >
        👎
      </button>
    </span>
  );
}

export function FindingCard({ finding, agentType, fieldDefinitions, forceOpen, feedbackValue, feedbackError, onFeedback }) {
  const [open, setOpen] = useState(false);
  const { t } = useI18n();
  const isOpen = forceOpen || open;
  const sev = (finding.severity || '').toLowerCase();

  return (
    <div
      class={`finding-card compact ${sev} ${isOpen ? 'open' : ''}`}
      onClick={() => setOpen(!open)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && setOpen(!open)}
    >
      <div class="finding-row">
        <span class="finding-id">{finding.id}</span>
        <span class="finding-title-inline">{finding.title}</span>
        <span class={`severity-badge ${sev}`}>
          {finding.severity}
        </span>
        {onFeedback && (
          <FeedbackButtons
            findingId={finding.id}
            currentValue={feedbackValue}
            onFeedback={onFeedback}
          />
        )}
        {feedbackError && (
          <span class="feedback-error" role="alert">{feedbackError}</span>
        )}
        <span class="finding-chevron">{isOpen ? '▾' : '▸'}</span>
      </div>
      {isOpen && (
        <div class="finding-detail">
          <div class="finding-tags">
            <DynamicBadges finding={finding} fieldDefinitions={fieldDefinitions} />
          </div>
          <div class="finding-description" dangerouslySetInnerHTML={{ __html: renderMarkdown(finding.description, 'chat') }} />
          {finding.recommendation && (
            <div class="finding-recommendation">
              <strong>{t('finding.recommendation')}</strong>
              <div dangerouslySetInnerHTML={{ __html: renderMarkdown(finding.recommendation, 'chat') }} />
            </div>
          )}
          <DynamicSections finding={finding} fieldDefinitions={fieldDefinitions} />
          {(finding.references || []).length > 0 && (
            <div class="finding-refs">
              {finding.references.map((r, i) => (
                <span key={i} class="finding-tag ref">{r}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
