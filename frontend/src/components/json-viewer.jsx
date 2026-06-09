import { useState } from 'preact/hooks';

/**
 * Modal that displays review results as formatted JSON with a download button.
 * Reuses existing .modal-overlay / .modal CSS classes.
 */
export function JsonViewerModal({ data, projectName, onClose }) {
  const [copied, setCopied] = useState(false);
  const jsonStr = JSON.stringify(data, null, 2);

  function handleDownload() {
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(projectName || 'review').replace(/\s+/g, '_')}_results.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleCopy() {
    navigator.clipboard.writeText(jsonStr).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div class="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()} onKeyDown={(e) => e.key === 'Escape' && onClose()} role="dialog" aria-modal="true">
      <div class="modal" style={{ maxWidth: '960px' }}>
        <div class="modal-header">
          <h3>📋 Review Results — JSON</h3>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button class="btn btn-secondary btn-small" onClick={handleCopy}>
              {copied ? '✓ Copied' : '📄 Copy'}
            </button>
            <button class="btn btn-primary btn-small" onClick={handleDownload}>
              ⬇ Download
            </button>
            <button class="modal-close" onClick={onClose}>✕</button>
          </div>
        </div>
        <div class="modal-body">
          <pre class="document-viewer">{jsonStr}</pre>
        </div>
      </div>
    </div>
  );
}
