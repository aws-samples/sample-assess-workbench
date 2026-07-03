// --- Agent config, visual primitives, and helpers for the review flow visualization ---

import { useMemo } from 'preact/hooks';
import { useAgents } from '../agent-context.jsx';
import { useI18n } from '../i18n-context.jsx';
import { fmtTokens } from '../lib/format-utils.js';
import { ProgressRing } from './progress-ring.jsx';

// Static infrastructure node keys (labels resolved via i18n at render time)
const INFRA_NODE_KEYS = {
  document_processing: { labelKey: 'flow.documentProcessing', icon: '📄', color: '#e67e22' },
  image_analysis:      { labelKey: 'flow.imageAnalysis',      icon: '🖼️', color: '#8e44ad' },
  orchestrator:  { labelKey: 'flow.orchestrator',  icon: '🎯', color: '#0066cc' },
  s3:            { labelKey: 'flow.s3Storage',     icon: '🗄️', color: '#e67e22' },
  memory:        { labelKey: 'flow.memory',        icon: '🧠', color: '#9b59b6' },
  registry:      { labelKey: 'flow.agentRegistry', icon: '📒', color: '#17a2b8' },
  quality_judge: { labelKey: 'flow.qualityJudge',  icon: '🔍', color: '#3498db' },
};

// Merged config: static infra (with translated labels) + dynamic agents from registry
export function useFlowAgents() {
  const { agents } = useAgents();
  const { t } = useI18n();
  return useMemo(() => ({
    ...Object.fromEntries(
      Object.entries(INFRA_NODE_KEYS).map(([key, cfg]) => [key, {
        label: t(cfg.labelKey), icon: cfg.icon, color: cfg.color,
      }])
    ),
    ...Object.fromEntries(
      Object.entries(agents).map(([key, a]) => [key, {
        label: a.display_name, icon: a.icon, color: a.color,
      }])
    ),
  }), [agents, t]);
}

// --- SVG Flow Line with animated particle ---
export function FlowLine({ from, to, active, color, bidirectional }) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  const pad = Math.min(44, len * 0.15);
  const ratio = pad / len;
  const x1 = from.x + dx * ratio;
  const y1 = from.y + dy * ratio;
  const x2 = to.x - dx * ratio;
  const y2 = to.y - dy * ratio;

  return (
    <g>
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={color}
        stroke-width={active ? 2.5 : 1.5}
      />
      {active && (
        <circle r="4" fill={color}>
          <animate attributeName="cx" from={x1} to={x2} dur="1.2s" repeatCount="indefinite" />
          <animate attributeName="cy" from={y1} to={y2} dur="1.2s" repeatCount="indefinite" />
        </circle>
      )}
      {active && bidirectional && (
        <circle r="3" fill={color} opacity="0.7">
          <animate attributeName="cx" from={x2} to={x1} dur="1.5s" repeatCount="indefinite" />
          <animate attributeName="cy" from={y2} to={y1} dur="1.5s" repeatCount="indefinite" />
        </circle>
      )}
    </g>
  );
}

// --- Agent Node Card ---
export function AgentNode({ agent, status, progress, style, expanded, depth, labelOverride, metrics, agentsMap, iterationBadge, toolCallsBadge, tooltip }) {
  const cfg = (agentsMap || {})[agent] || { label: agent, icon: '🔍', color: '#888' };
  const statusClass = status === 'active' ? 'rv-node--active'
    : status === 'done' ? 'rv-node--done'
    : status === 'warning' ? 'rv-node--warning'
    : status === 'error' ? 'rv-node--error' : '';
  return (
    <div class={`rv-node ${statusClass}`} style={{ ...style, '--node-color': cfg.color }} title={tooltip || ''}>
      {status === 'done' && <span class="rv-node-check">✓</span>}
      {status === 'warning' && <span class="rv-node-check">⚠</span>}
      {status === 'error' && <span class="rv-node-check">✗</span>}
      <span class="rv-node-icon">{cfg.icon}</span>
      <span class="rv-node-label">{labelOverride || cfg.label}</span>
      {expanded && depth && (
        <span class="rv-node-depth" style="font-size:0.7rem;opacity:0.7;margin-top:2px">{{ quick: 'quick', standard: 'standard', thorough: 'deep' }[depth] || depth}</span>
      )}
      {status === 'active' && progress > 0 && (
        <ProgressRing progress={progress} color={cfg.color} size={32} />
      )}
      {status === 'done' && metrics && metrics.total_tokens > 0 && (
        <div class="rv-node-metrics">
          <span>{fmtTokens(metrics.total_tokens)} tok</span>
          {metrics.cycle_count > 0 && <span>{metrics.cycle_count} cyc</span>}
        </div>
      )}
      {iterationBadge && (
        <span class={`rv-iteration-badge ${iterationBadge.status === 'pass' ? 'rv-iteration-badge--pass' : iterationBadge.status === 'fail' ? 'rv-iteration-badge--fail' : ''}`}>
          {iterationBadge.status === 'pass' ? `✓${iterationBadge.iteration}` : `✗${iterationBadge.iteration}`}
        </span>
      )}
      {toolCallsBadge && (
        <span class="rv-tool-badge" title={toolCallsBadge.tooltip}>🔧 {toolCallsBadge.total}</span>
      )}
    </div>
  );
}

// --- Document Processing Node (shows file-by-file progress) ---
export function DocProcessingNode({ status, progress, style, fileEvents }) {
  const { t } = useI18n();
  const cfg = { label: t('flow.documentProcessing'), icon: '📄', color: '#e67e22' };
  const statusClass = status === 'active' ? 'rv-node--active'
    : status === 'done' ? 'rv-node--done'
    : status === 'error' ? 'rv-node--error' : '';

  // Build summary from completed events
  const summary = fileEvents?.summary;

  return (
    <div class={`rv-node rv-node--doc-processing ${statusClass}`} style={{ ...style, '--node-color': cfg.color }}>
      {status === 'done' && <span class="rv-node-check">✓</span>}
      <span class="rv-node-icon">{cfg.icon}</span>
      <span class="rv-node-label">{cfg.label}</span>

      {/* File progress list */}
      {status === 'active' && fileEvents?.files?.length > 0 && (
        <ul class="doc-file-list">
          {fileEvents.files.map((f, i) => (
            <li key={i} class={`doc-file-item ${f.done ? 'doc-file-item--done' : ''}`}>
              <span class="doc-file-icon">{f.type === 'pdf' ? '📕' : '📄'}</span>
              <span class="doc-file-name">{f.filename}</span>
              {f.done && f.pages > 0 && <span class="doc-file-meta">{f.pages}p</span>}
              {f.done && <span class="doc-file-check">✓</span>}
            </li>
          ))}
        </ul>
      )}

      {/* Completion summary */}
      {status === 'done' && summary && (
        <div class="doc-summary">
          {t('flow.docSummary', { files: summary.total_files, pages: summary.total_pages, images: summary.total_images })}
        </div>
      )}

      {status === 'active' && progress > 0 && (
        <ProgressRing progress={progress} color={cfg.color} size={32} />
      )}
    </div>
  );
}

// Category icons for image classification results
const CATEGORY_ICONS = {
  architecture_diagram: '📐', sequence_diagram: '🔄', flowchart: '🔀',
  uml: '📊', network_diagram: '🌐', data_flow: '📡', er_diagram: '🗃️',
  logo: '🏷️', decorative: '🎨', screenshot: '📸', photo: '📷', other: '❓',
};

// --- Image Analysis Node (shows per-image triage + analysis progress) ---
export function ImageAnalysisNode({ status, progress, style, imageEvents }) {
  const { t } = useI18n();
  const cfg = { label: t('flow.imageAnalysis'), icon: '🖼️', color: '#8e44ad' };
  const statusClass = status === 'active' ? 'rv-node--active'
    : status === 'done' ? 'rv-node--done'
    : status === 'error' ? 'rv-node--error' : '';

  const summary = imageEvents?.summary;
  const images = imageEvents?.images || [];

  return (
    <div class={`rv-node rv-node--image-analysis ${statusClass}`} style={{ ...style, '--node-color': cfg.color }}>
      {status === 'done' && <span class="rv-node-check">✓</span>}
      {status === 'error' && <span class="rv-node-check">✗</span>}
      <span class="rv-node-icon">{cfg.icon}</span>
      <span class="rv-node-label">{cfg.label}</span>

      {/* Per-image progress list */}
      {status === 'active' && images.length > 0 && (
        <ul class="img-analysis-list">
          {images.slice(-4).map((img, i) => (
            <li key={i} class={`img-analysis-item ${img.status === 'analyzed' ? 'img-analysis-item--done' : ''} ${img.status === 'skipped' ? 'img-analysis-item--skipped' : ''}`}>
              <span class="img-analysis-icon">{CATEGORY_ICONS[img.category] || '❓'}</span>
              <span class="img-analysis-label" title={img.brief_description || img.category}>
                {img.status === 'analyzing' ? t('flow.analyzing') : img.category?.replace(/_/g, ' ') || '?'}
              </span>
              {img.status === 'analyzed' && <span class="img-analysis-check">✓</span>}
              {img.status === 'skipped' && <span class="img-analysis-skip">⊘</span>}
            </li>
          ))}
        </ul>
      )}

      {/* Completion summary */}
      {status === 'done' && summary && (
        <div class="img-analysis-summary">
          {t('flow.imgSummary', { analyzed: summary.analyzed, skipped: summary.skipped })}
          {summary.total_tokens > 0 && <span> · {fmtTokens(summary.total_tokens)} tok</span>}
        </div>
      )}

      {status === 'active' && progress > 0 && (
        <ProgressRing progress={progress} color={cfg.color} size={32} />
      )}
    </div>
  );
}
