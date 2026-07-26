import { useEffect, useMemo, useRef, useState } from 'react';
import type { Options as ReactMarkdownOptions } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { hasMarkdownMathSyntax } from './markdownMathModel';

type RemarkPlugin = NonNullable<ReactMarkdownOptions['remarkPlugins']>[number];
type RehypePlugin = NonNullable<ReactMarkdownOptions['rehypePlugins']>[number];

type LoadedMathPlugins = {
  remarkMath: RemarkPlugin;
  rehypeKatex: RehypePlugin;
};

const BASE_REMARK_PLUGINS: NonNullable<ReactMarkdownOptions['remarkPlugins']> = [
  remarkGfm,
];
const BASE_REHYPE_PLUGINS: NonNullable<ReactMarkdownOptions['rehypePlugins']> = [];

let cachedMathPlugins: LoadedMathPlugins | null = null;
let mathLoadPromise: Promise<LoadedMathPlugins> | null = null;

async function loadMathPlugins(): Promise<LoadedMathPlugins> {
  if (cachedMathPlugins) return cachedMathPlugins;
  if (!mathLoadPromise) {
    mathLoadPromise = Promise.all([
      import('remark-math'),
      import('rehype-katex'),
      import('katex/dist/katex.min.css'),
    ])
      .then(([remarkMathModule, rehypeKatexModule]) => {
        cachedMathPlugins = {
          remarkMath: remarkMathModule.default as RemarkPlugin,
          rehypeKatex: rehypeKatexModule.default as RehypePlugin,
        };
        return cachedMathPlugins;
      })
      .catch((cause: unknown) => {
        mathLoadPromise = null;
        throw cause;
      });
  }
  return mathLoadPromise;
}

export function useMarkdownMathPlugins(content: string) {
  const [mathLoaded, setMathLoaded] = useState(Boolean(cachedMathPlugins));
  const loadAttempted = useRef(false);
  const hasMath = useMemo(() => hasMarkdownMathSyntax(content), [content]);

  useEffect(() => {
    let cancelled = false;
    if (hasMath && cachedMathPlugins) {
      setMathLoaded(true);
    } else if (hasMath && !loadAttempted.current) {
      loadAttempted.current = true;
      void loadMathPlugins()
        .then(() => {
          if (!cancelled) setMathLoaded(true);
        })
        .catch(() => {
          // Preserve the raw Markdown delimiters when optional rendering cannot load.
        });
    }
    return () => {
      cancelled = true;
    };
  }, [hasMath]);

  return useMemo(() => {
    if (mathLoaded && cachedMathPlugins) {
      return {
        remarkPlugins: [...BASE_REMARK_PLUGINS, cachedMathPlugins.remarkMath],
        rehypePlugins: [cachedMathPlugins.rehypeKatex],
      };
    }
    return {
      remarkPlugins: BASE_REMARK_PLUGINS,
      rehypePlugins: BASE_REHYPE_PLUGINS,
    };
  }, [mathLoaded]);
}
