import { useState, useEffect, useRef, useCallback } from 'preact/hooks';

/**
 * Measures a container's width via ResizeObserver and computes a scale factor
 * so that content of a known pixel width fits within the container.
 *
 * @param {number} contentWidth - The natural pixel width of the content.
 * @returns {{ containerRef: import('preact').RefObject, scale: number }}
 */
export function useContainerScale(contentWidth) {
  const containerRef = useRef(null);
  const [scale, setScale] = useState(1);

  const updateScale = useCallback((width) => {
    if (contentWidth > 0 && width > 0) {
      setScale(width / contentWidth);
    }
  }, [contentWidth]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        updateScale(entry.contentRect.width);
      }
    });

    ro.observe(el);
    // Initial measurement
    updateScale(el.clientWidth);

    return () => ro.disconnect();
  }, [updateScale]);

  return { containerRef, scale };
}
