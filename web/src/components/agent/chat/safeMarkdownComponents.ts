import type { Components } from 'react-markdown';

import { MarkdownTable, SandboxImage } from './markdownComponentRenderers';

/**
 * Safe img component that resolves sandbox paths and suppresses empty src warnings.
 * Markdown like `![]()` produces `<img src="">` which triggers a React warning
 * and causes the browser to re-fetch the current page.
 */
export const safeMarkdownComponents: Partial<Components> = {
  img: SandboxImage,
  table: MarkdownTable,
};
