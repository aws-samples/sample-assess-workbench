import { useState, useRef, useCallback } from 'preact/hooks';

/**
 * Resizable split panel with a draggable divider.
 *
 * @param {object} props
 * @param {number} [props.defaultSplit=50] - Initial left panel width as a percentage.
 * @param {number} [props.minLeft=20] - Minimum left panel percentage.
 * @param {number} [props.maxLeft=80] - Maximum left panel percentage.
 * @param {import('preact').ComponentChildren} props.children - Exactly two children: left and right panels.
 */
export function SplitPanel({ defaultSplit = 50, minLeft = 20, maxLeft = 80, className, style, children }) {
  const [splitPct, setSplitPct] = useState(defaultSplit);
  const splitRef = useRef(null);
  const dragging = useRef(false);

  const onMouseDown = useCallback((e) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev) => {
      if (!dragging.current || !splitRef.current) return;
      const rect = splitRef.current.getBoundingClientRect();
      const pct = ((ev.clientX - rect.left) / rect.width) * 100;
      setSplitPct(Math.min(maxLeft, Math.max(minLeft, pct)));
    };

    const onMouseUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [minLeft, maxLeft]);

  const left = Array.isArray(children) ? children[0] : children;
  const right = Array.isArray(children) ? children[1] : null;

  return (
    <div
      class={`split-panel ${className || ''}`}
      ref={splitRef}
      style={{ gridTemplateColumns: `${splitPct}% 8px 1fr`, ...style }}
    >
      <div class="split-panel-left">{left}</div>
      {/* role="separator" is interactive (ARIA widget role) — tabIndex and mouse/key handlers are correct.
          eslint's jsx-a11y doesn't recognise separator as interactive, so we disable the false positive. */}
      {/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
      <div
        class="split-handle"
        role="separator"
        aria-orientation="vertical"
        tabIndex={0}
        onMouseDown={onMouseDown}
        onKeyDown={(e) => e.key === 'Enter' && onMouseDown(e)}
      >
        <div class="split-handle-grip" />
      </div>
      {/* eslint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex */}
      <div class="split-panel-right">{right}</div>
    </div>
  );
}
