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

/**
 * Sanitize generated SVG while preserving chart geometry/text.
 *
 * DOMPurify's default HTML profile can strip SVG children in tests and some
 * browser-like runtimes, so Mermaid output gets a narrow SVG pass here.
 */
export function sanitizeSvg(dirty: string): string {
  const parser = new DOMParser();
  const document = parser.parseFromString(dirty, 'image/svg+xml');
  const parserError = document.querySelector('parsererror');
  const root = document.documentElement;

  if (parserError || root.nodeName.toLowerCase() !== 'svg') {
    return '';
  }

  const blockedTags = new Set(['script', 'foreignobject', 'iframe', 'object', 'embed']);
  const blockedUrlPattern = /^\s*(?:javascript|data:text\/html)/i;

  const sanitizeElement = (element: Element): void => {
    const tagName = element.tagName.toLowerCase();
    if (blockedTags.has(tagName)) {
      element.remove();
      return;
    }

    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value;

      if (
        name.startsWith('on') ||
        name === 'srcdoc' ||
        ((name === 'href' || name === 'xlink:href') && blockedUrlPattern.test(value))
      ) {
        element.removeAttribute(attribute.name);
      }
    }

    for (const child of Array.from(element.children)) {
      sanitizeElement(child);
    }
  };

  sanitizeElement(root);

  return new XMLSerializer().serializeToString(root);
}
