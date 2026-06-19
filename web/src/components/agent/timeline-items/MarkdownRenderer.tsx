import { lazy } from 'react';

import ReactMarkdown from 'react-markdown';

import remarkGfm from 'remark-gfm';

import { safeMarkdownComponents } from '../chat/safeMarkdownComponents';

// Lazy load math-only markdown extras to reduce initial bundle size.
const LazyMarkdownRenderer = lazy(async () => {
  const [{ default: remarkMath }, { default: rehypeKatex }] = await Promise.all([
    import('remark-math'),
    import('rehype-katex'),
  ]);
  await import('katex/dist/katex.min.css');

  const MarkdownWrapper = ({ children }: { children: string }) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={safeMarkdownComponents}
    >
      {children}
    </ReactMarkdown>
  );

  return { default: MarkdownWrapper };
});

export function MarkdownRenderer({ children }: { children: string }) {
  return <LazyMarkdownRenderer>{children}</LazyMarkdownRenderer>;
}
