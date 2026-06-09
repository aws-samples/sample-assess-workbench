// --- Progress Ring — pure SVG radial progress indicator with percentage label ---

export function ProgressRing({ progress, color, size = 36 }) {
  const r = (size - 4) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - progress);
  const pct = Math.round(progress * 100);
  return (
    <div class="rv-node-progress">
      <svg width={size} height={size} class="progress-ring">
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#333" stroke-width="3" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} stroke-width="3"
          stroke-dasharray={circ} stroke-dashoffset={offset} stroke-linecap="round"
          transform={`rotate(-90 ${size/2} ${size/2})`}
          style="transition: stroke-dashoffset 0.3s ease;" />
      </svg>
      <span class="rv-node-pct">{pct}%</span>
    </div>
  );
}
