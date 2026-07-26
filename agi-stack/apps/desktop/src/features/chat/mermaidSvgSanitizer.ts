const ALLOWED_SVG_TAGS = new Set([
  'svg',
  'g',
  'path',
  'rect',
  'circle',
  'ellipse',
  'polygon',
  'polyline',
  'line',
  'text',
  'tspan',
  'title',
  'desc',
  'defs',
  'marker',
  'lineargradient',
  'radialgradient',
  'stop',
  'clippath',
  'mask',
  'pattern',
  'use',
  'style',
]);

const ALLOWED_SVG_ATTRIBUTES = new Set([
  'id',
  'class',
  'style',
  'viewbox',
  'width',
  'height',
  'x',
  'y',
  'x1',
  'y1',
  'x2',
  'y2',
  'cx',
  'cy',
  'r',
  'rx',
  'ry',
  'd',
  'points',
  'transform',
  'fill',
  'stroke',
  'stroke-width',
  'stroke-linecap',
  'stroke-linejoin',
  'stroke-dasharray',
  'opacity',
  'fill-opacity',
  'stroke-opacity',
  'font-family',
  'font-size',
  'font-weight',
  'text-anchor',
  'dominant-baseline',
  'marker-start',
  'marker-mid',
  'marker-end',
  'orient',
  'refx',
  'refy',
  'markerwidth',
  'markerheight',
  'preserveaspectratio',
  'gradientunits',
  'offset',
  'stop-color',
  'stop-opacity',
  'clip-path',
  'mask',
  'role',
  'aria-label',
  'aria-labelledby',
  'xmlns',
  'href',
  'xlink:href',
]);

const BLOCKED_SVG_TAGS = new Set([
  'script',
  'foreignobject',
  'iframe',
  'object',
  'embed',
  'audio',
  'video',
  'image',
  'animate',
  'animatemotion',
  'animatetransform',
  'set',
]);

const BLOCKED_URL_PATTERN = /^\s*(?:javascript|data:text\/html)/i;
const BLOCKED_CSS_PATTERN = /(?:javascript|data:text\/html|expression\s*\(|@import)/i;
const NON_FRAGMENT_CSS_URL_PATTERN = /url\s*\(\s*(?!['"]?#)/i;

function safeFragmentReference(value: string): boolean {
  return /^\s*#[A-Za-z_][\w:.-]*\s*$/u.test(value);
}

function safeCss(value: string): boolean {
  return !BLOCKED_CSS_PATTERN.test(value) && !NON_FRAGMENT_CSS_URL_PATTERN.test(value);
}

function sanitizeElement(element: Element): void {
  const tagName = element.tagName.toLowerCase();
  if (BLOCKED_SVG_TAGS.has(tagName) || !ALLOWED_SVG_TAGS.has(tagName)) {
    element.remove();
    return;
  }

  for (const attribute of Array.from(element.attributes)) {
    const name = attribute.name.toLowerCase();
    const value = attribute.value;
    const href = name === 'href' || name === 'xlink:href';
    if (
      name.startsWith('on') ||
      !ALLOWED_SVG_ATTRIBUTES.has(name) ||
      (href && (!safeFragmentReference(value) || BLOCKED_URL_PATTERN.test(value))) ||
      (name === 'style' && !safeCss(value))
    ) {
      element.removeAttribute(attribute.name);
    }
  }

  if (tagName === 'style' && !safeCss(element.textContent ?? '')) {
    element.remove();
    return;
  }

  for (const child of Array.from(element.children)) {
    sanitizeElement(child);
  }
}

/** Return a narrow, inert SVG document or an empty string when parsing fails. */
export function sanitizeMermaidSvg(dirty: string): string {
  const parser = new DOMParser();
  const document = parser.parseFromString(dirty, 'image/svg+xml');
  const root = document.documentElement;
  if (document.querySelector('parsererror') || root.tagName.toLowerCase() !== 'svg') {
    return '';
  }

  sanitizeElement(root);
  if (!root.isConnected) return '';
  return new XMLSerializer().serializeToString(root);
}
