/**
 * HTML sanitization utilities using DOMPurify.
 *
 * Prevents XSS when rendering user-supplied or LLM-generated HTML.
 */
import DOMPurify from 'dompurify';

/**
 * Sanitize an HTML string, stripping dangerous elements and attributes.
 *
 * Allowed by default: standard inline/block HTML, images, links.
 * Stripped: `<script>`, `<iframe>`, event handlers (`onerror`, `onclick`, etc.).
 */
export function sanitizeHtml(dirty: string): string {
  return DOMPurify.sanitize(dirty);
}
