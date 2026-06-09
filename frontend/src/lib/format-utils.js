// Shared formatting utilities for the review visualization.

/** Format token count compactly (e.g. 12345 → "12.3K") */
export function fmtTokens(n) {
  if (!n) return '0';
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
  return String(n);
}
