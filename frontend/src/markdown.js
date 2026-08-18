import { marked } from 'marked';
import DOMPurify from 'dompurify';

marked.setOptions({ breaks: true, gfm: true });

/**
 * Render markdown to sanitized HTML.
 * @param {string} text - raw markdown
 * @param {'chat'|'docs'} mode - chat uses a tight allowlist; docs allows richer HTML
 */
export function renderMarkdown(text, mode = 'docs') {
  const raw = marked.parse(text || '');
  if (mode === 'chat') {
    return DOMPurify.sanitize(raw, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's', 'del',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote',
        'pre', 'code', 'a', 'span',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'hr', 'div',
      ],
      ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
    });
  }
  return DOMPurify.sanitize(raw);
}
