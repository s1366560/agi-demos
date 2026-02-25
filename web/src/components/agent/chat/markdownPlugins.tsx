/**
 * Shared markdown plugin configuration.
 *
 * Single source of truth for remark/rehype plugins used across all
 * ReactMarkdown instances. Import these arrays instead of configuring
 * plugins individually in each component.
 *
 * KaTeX (math rendering) is lazy-loaded on demand to reduce the initial
 * bundle size by ~300KB. Use the `useMarkdownPlugins` hook which detects
 * math content and loads KaTeX only when needed.
 */

import { useMemo, useRef, useState, useEffect } from 'react';

import type { Components } from 'react-markdown';

import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';


/**
 * Rehype plugin that strips empty `data` attributes from elements.
 * Prevents React warning: "An empty string was passed to the data attribute."
 */
function rehypeStripEmptyData() {
  interface HastNode {
    type: string;
    properties?: Record<string, unknown>;
    children?: HastNode[];
  }
  return (tree: HastNode) => {
    const visit = (node: HastNode) => {
      if (node.type === 'element' && node.properties && 'data' in node.properties) {
        if (node.properties.data === '') {
          delete node.properties.data;
        }
      }
      if (node.children) {
        for (const child of node.children) visit(child);
      }
    };
    visit(tree);
  };
}

// Base plugins (always loaded)
const baseRemarkPlugins = [remarkGfm];
const baseRehypePlugins = [rehypeRaw, rehypeStripEmptyData];

// Cached math plugins after lazy load
type RemarkPlugin = typeof remarkGfm;
type RehypePlugin = typeof rehypeRaw;
let cachedMathPlugins: { remarkMath: RemarkPlugin; rehypeKatex: RehypePlugin } | null = null;
let mathLoadPromise: Promise<{ remarkMath: RemarkPlugin; rehypeKatex: RehypePlugin }> | null = null;

const MATH_PATTERN = /\$\$[\s\S]+?\$\$|\$[^\s$].*?[^\s$]\$/;

async function loadMathPlugins() {
  if (cachedMathPlugins) return cachedMathPlugins;
  if (!mathLoadPromise) {
    mathLoadPromise = Promise.all([
      import('remark-math'),
      import('rehype-katex'),
      import('katex/dist/katex.min.css'),
    ]).then(([remarkMathMod, rehypeKatexMod]) => {
      cachedMathPlugins = {
        remarkMath: remarkMathMod.default as RemarkPlugin,
        rehypeKatex: rehypeKatexMod.default as unknown as RehypePlugin,
      };
      return cachedMathPlugins;
    });
  }
  return mathLoadPromise;
}

/**
 * Hook that returns markdown plugins, lazily loading KaTeX when math is detected.
 */
export function useMarkdownPlugins(content?: string) {
  const [mathLoaded, setMathLoaded] = useState(!!cachedMathPlugins);
  const hasMath = content ? MATH_PATTERN.test(content) : false;
  const loadAttempted = useRef(false);

  useEffect(() => {
    if (hasMath && !cachedMathPlugins && !loadAttempted.current) {
      loadAttempted.current = true;
      void loadMathPlugins().then(() => { setMathLoaded(true); });
    }
  }, [hasMath]);

  return useMemo(() => {
    if (mathLoaded && cachedMathPlugins) {
      return {
        remarkPlugins: [...baseRemarkPlugins, cachedMathPlugins.remarkMath],
        rehypePlugins: [...baseRehypePlugins, cachedMathPlugins.rehypeKatex],
      };
    }
    return {
      remarkPlugins: baseRemarkPlugins,
      rehypePlugins: baseRehypePlugins,
    };
  }, [mathLoaded]);
}

// Legacy static exports (without KaTeX - use useMarkdownPlugins hook instead)
export const remarkPlugins = baseRemarkPlugins;
export const rehypePlugins = baseRehypePlugins;

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
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto w-full">
      <table {...props}>{children}</table>
    </div>
  ),
};
