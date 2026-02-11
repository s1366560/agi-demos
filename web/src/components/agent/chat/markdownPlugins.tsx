/**
 * Shared markdown plugin configuration.
 *
 * Single source of truth for remark/rehype plugins used across all
 * ReactMarkdown instances. Import these arrays instead of configuring
 * plugins individually in each component.
 */

import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';

import 'katex/dist/katex.min.css';

export const remarkPlugins = [remarkGfm, remarkMath];

export const rehypePlugins = [rehypeRaw, rehypeKatex];

/**
 * Safe img component that suppresses empty src warnings.
 * Markdown like `![]()` produces `<img src="">` which triggers a React warning
 * and causes the browser to re-fetch the current page.
 */
export const safeMarkdownComponents: Partial<Components> = {
  img: ({ src, ...props }) => {
    if (!src) return null;
    return <img src={src} {...props} />;
  },
};
