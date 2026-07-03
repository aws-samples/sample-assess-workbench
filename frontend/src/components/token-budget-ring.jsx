/**
 * Token budget ring — shows context window consumption as a circular
 * progress indicator with model name. Uses real token counts from the
 * backend `usage` WebSocket event.
 *
 * Hidden until the first usage event arrives for the current session.
 * Resets on session switch.
 */

// Context-window + display metadata keyed by the prefix-stripped model ID.
// Bedrock cross-Region inference IDs carry a geo/global prefix
// (us./eu./au./jp./global.) that we strip before lookup, so the same entry
// matches regardless of which Region the stack is deployed to.
const MODEL_INFO = {
  'anthropic.claude-sonnet-4-6': { name: 'Claude Sonnet 4', contextWindow: 200_000 },
  'anthropic.claude-haiku-4-5-20251001-v1:0': { name: 'Claude Haiku 4.5', contextWindow: 200_000 },
  'anthropic.claude-sonnet-4-20250514-v1:0': { name: 'Claude Sonnet 4', contextWindow: 200_000 },
};

// Strip the cross-Region inference-profile prefix so a model matches
// MODEL_INFO regardless of the deploy Region (e.g. global./au. → bare ID).
function stripInferencePrefix(modelId) {
  return modelId ? modelId.replace(/^(us|eu|au|jp|apac|global)\./, '') : modelId;
}

const SIZE = 20;
const STROKE = 2.5;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function fmtTokens(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function TokenBudgetRing({ usage, modelId }) {
  if (!usage) return null;

  const tokensUsed = (usage.input_tokens || 0) + (usage.output_tokens || 0);
  const info = MODEL_INFO[stripInferencePrefix(modelId)];

  if (!info && modelId) {
    console.warn(`[TokenBudgetRing] Unknown model ID: ${modelId}`);
  }

  const contextWindow = info?.contextWindow;
  const modelName = info?.name || modelId || 'Unknown model';
  const pct = contextWindow ? Math.min(tokensUsed / contextWindow, 1) : null;
  const offset = pct !== null ? CIRCUMFERENCE * (1 - pct) : CIRCUMFERENCE;

  const colorClass = pct === null ? '' : pct > 0.9 ? 'ring-danger' : pct > 0.75 ? 'ring-warning' : '';
  const label = pct !== null
    ? `${Math.round(pct * 100)}% · ${modelName}`
    : `${fmtTokens(tokensUsed)} tokens · ${modelName}`;
  const tooltip = contextWindow
    ? `~${fmtTokens(tokensUsed)} / ${fmtTokens(contextWindow)} tokens used`
    : `${fmtTokens(tokensUsed)} tokens used`;

  return (
    <div class={`token-budget ${colorClass}`} title={tooltip}>
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} class="token-ring-svg">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS}
          fill="none" stroke="currentColor" stroke-width={STROKE} opacity="0.15" />
        {pct !== null && (
          <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS}
            fill="none" stroke="currentColor" stroke-width={STROKE}
            stroke-dasharray={CIRCUMFERENCE} stroke-dashoffset={offset}
            stroke-linecap="round"
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`} />
        )}
      </svg>
      <span class="token-budget-label">{label}</span>
    </div>
  );
}
