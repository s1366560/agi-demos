/**
 * Shared markdown plugin configuration.
 *
 * Single source of truth for remark/rehype plugins used across all
 * ReactMarkdown instances. Import these arrays instead of configuring
 * plugins individually in each component.
 */

import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

import 'katex/dist/katex.min.css';

export const remarkPlugins = [remarkGfm, remarkMath];

export const rehypePlugins = [rehypeKatex];
