/**
 * Shared utility functions for tool result parsing
 *
 * Extracted from ToolExecutionCard and ToolExecutionDetail
 * to eliminate code duplication.
 */

/**
 * Check if a string is an image URL
 *
 * @param str - String to check
 * @returns true if the string is an image URL
 */
export function isImageUrl(str: string): boolean {
  if (!str) return false;
  const trimmed = str.trim();
  // Check for common image URL patterns
  const imageExtensions = /\.(jpg|jpeg|png|gif|webp|svg|bmp|ico)(\?.*)?$/i;
  const imageHosts = [
    'mdn.alipayobjects.com',
    'img.alicdn.com',
    'cdn.jsdelivr.net',
    'i.imgur.com',
    'images.unsplash.com',
  ];

  try {
    const url = new URL(trimmed);
    // Check by extension
    if (imageExtensions.test(url.pathname)) return true;
    // Check by known image hosts
    if (imageHosts.some((host) => url.hostname.includes(host))) return true;
    // Check for /original suffix (common in CDN image URLs)
    if (url.pathname.endsWith('/original')) return true;
  } catch {
    return false;
  }
  return false;
}

/**
 * Parse base64 image data from tool result
 *
 * @param result - Result string potentially containing base64 image data
 * @returns Object with data and format, or null if not a base64 image
 */
export function parseBase64Image(result: string): { data: string; format: string } | null {
  try {
    // Try to parse as JSON first (e.g., {'data': 'base64...'})
    const jsonMatch = result.match(/\{[\s\S]*['"]data['"]:\s*['"]([A-Za-z0-9+/=]+)['"][\s\S]*\}/);
    if (jsonMatch && jsonMatch[1]) {
      const base64Data = jsonMatch[1];
      // Detect image format from base64 header
      if (base64Data.startsWith('iVBORw0KGgo')) return { data: base64Data, format: 'png' };
      if (base64Data.startsWith('/9j/')) return { data: base64Data, format: 'jpeg' };
      if (base64Data.startsWith('R0lGOD')) return { data: base64Data, format: 'gif' };
      if (base64Data.startsWith('UklGR')) return { data: base64Data, format: 'webp' };
      // Default to PNG
      return { data: base64Data, format: 'png' };
    }

    // Check if result itself is base64 (no JSON wrapper)
    const base64Only = result.trim();
    if (/^[A-Za-z0-9+/=]+$/.test(base64Only) && base64Only.length > 100) {
      if (base64Only.startsWith('iVBORw0KGgo')) return { data: base64Only, format: 'png' };
      if (base64Only.startsWith('/9j/')) return { data: base64Only, format: 'jpeg' };
      if (base64Only.startsWith('R0lGOD')) return { data: base64Only, format: 'gif' };
      if (base64Only.startsWith('UklGR')) return { data: base64Only, format: 'webp' };
      return { data: base64Only, format: 'png' };
    }
  } catch {
    // Fall through
  }
  return null;
}

/**
 * Extract image URL from result text
 *
 * @param result - Result string potentially containing an image URL
 * @returns The image URL, or null if none found
 */
export function extractImageUrl(result: string): string | null {
  if (!result) return null;
  const trimmed = result.trim();

  // If the entire result is an image URL
  if (isImageUrl(trimmed)) return trimmed;

  // Try to extract URL from text
  const urlMatch = trimmed.match(/https?:\/\/[^\s<>"']+/g);
  if (urlMatch) {
    for (const url of urlMatch) {
      if (isImageUrl(url)) return url;
    }
  }
  return null;
}

/**
 * Fold long text by keeping first and last N lines
 *
 * @param text - Text to fold
 * @param keepLines - Number of lines to keep at start and end (default: 5)
 * @returns Folded text string
 */
export function foldText(text: string | undefined, keepLines: number = 5): string {
  if (!text) return '';
  const lines = text.split('\n');
  const totalLines = lines.length;

  if (totalLines <= keepLines * 2) {
    return text;
  }

  const firstLines = lines.slice(0, keepLines);
  const lastLines = lines.slice(-keepLines);
  const foldedCount = totalLines - keepLines * 2;

  return [...firstLines, `\n... (${foldedCount} lines collapsed) ...\n`, ...lastLines].join('\n');
}

/**
 * Fold long text with metadata about whether folding occurred
 *
 * @param text - Text to fold
 * @param keepLines - Number of lines to keep at start and end (default: 5)
 * @returns Object with folded text and boolean indicating if folding occurred
 */
export function foldTextWithMetadata(
  text: string | undefined,
  keepLines: number = 5
): { text: string; folded: boolean } {
  if (!text) return { text: '', folded: false };
  const lines = text.split('\n');
  const totalLines = lines.length;

  if (totalLines <= keepLines * 2) {
    return { text, folded: false };
  }

  const firstLines = lines.slice(0, keepLines);
  const lastLines = lines.slice(-keepLines);
  const foldedCount = totalLines - keepLines * 2;

  return {
    text: [...firstLines, `\n... (${foldedCount} lines collapsed) ...\n`, ...lastLines].join('\n'),
    folded: true,
  };
}

// Attach metadata method to foldText for compatibility
foldText.withMetadata = foldTextWithMetadata;
