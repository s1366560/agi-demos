/**
 * MarkdownContent - Unified Markdown rendering component
 *
 * Provides consistent Markdown rendering across the application with:
 * - GitHub Flavored Markdown (GFM) support (tables, strikethrough, task lists)
 * - Proper styling for links and images
 * - Syntax highlighting support (via prose classes)
 * - Code block actions (Copy, Open in Canvas)
 * - Lazy loading for heavy components (mermaid, math)
 * - Memoization for performance
 *
 * This component can be reused in:
 * - AssistantMessage
 * - ToolExecutionCardDisplay (for tool results)
 * - FinalResponseDisplay
 *
 * @example
 * // Full prose styling with code actions (for message content)
 * <MarkdownContent content="# Header\n\n```js\nconst x = 1;\n```" prose codeActions />
 *
 * @example
 * // Minimal styling (for inline or tool results)
 * <MarkdownContent content="**Result:** Done" className="text-xs" />
 */

import { memo, useMemo, lazy, Suspense, useCallback } from 'react';

import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { MARKDOWN_PROSE_CLASSES } from '../styles';

import { useMarkdownPlugins } from './markdownPlugins';


export interface MarkdownContentProps {
  /** Markdown content to render */
  content: string;
  /** Additional CSS classes for the container */
  className?: string;
  /** Whether to enable full prose styling */
  prose?: boolean;
  /** Whether to show code block actions (copy, open in canvas) */
  codeActions?: boolean;
  /** Loading fallback for lazy components */
  loadingFallback?: React.ReactNode;
}

/**
 * Loading fallback for lazy-loaded components.
 */
const CodeBlockLoadingFallback: React.FC = () => (
  <div className="my-2 p-3 bg-slate-100 dark:bg-slate-800 rounded-lg animate-pulse">
    <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded w-24 mb-2" />
    <div className="space-y-1">
      <div className="h-3 bg-slate-200 dark:bg-slate-700 rounded" />
      <div className="h-3 bg-slate-200 dark:bg-slate-700 rounded w-5/6" />
      <div className="h-3 bg-slate-200 dark:bg-slate-700 rounded w-4/6" />
    </div>
  </div>
);

/**
 * Lazy-loaded CodeBlock with Suspense.
 * Code blocks are heavy due to syntax highlighting, so we lazy load them.
 */
const CodeBlockWithSuspense = memo<{
  children?: React.ReactNode;
  codeActions?: boolean;
  loadingFallback?: React.ReactNode;
}>(({ children, codeActions = false, loadingFallback }) => {
  const LazyCodeBlock = useMemo(
    () => lazy(() => import('./CodeBlock').then((module) => ({ default: module.CodeBlock }))),
    []
  );

  return (
    <Suspense fallback={loadingFallback || <CodeBlockLoadingFallback />}>
      <LazyCodeBlock codeActions={codeActions}>{children}</LazyCodeBlock>
    </Suspense>
  );
});

CodeBlockWithSuspense.displayName = 'CodeBlockWithSuspense';

/**
 * Create code components with memoization.
 */
const useCodeComponents = memo(({ codeActions }: { codeActions: boolean }) => {
  const components: Components = useMemo(
    () => ({
      pre: ({ children, ...props }) => (
        <CodeBlockWithSuspense codeActions={codeActions}>{children}</CodeBlockWithSuspense>
      ),
    }),
    [codeActions]
  );
  return components;
});

useCodeComponents.displayName = 'useCodeComponents';

/**
 * MarkdownContent component
 * 
 * Optimizations:
 * - React.memo prevents re-renders when props haven't changed
 * - Lazy loading for heavy components (CodeBlock)
 * - useMemo for plugin initialization
 * - useCallback for stable event handlers
 */
export const MarkdownContent = memo<MarkdownContentProps>(
  ({ content, className = '', prose = true, codeActions = false, loadingFallback }) => {
    const combinedClassName = prose ? `${MARKDOWN_PROSE_CLASSES} ${className}`.trim() : className;
    const CodeComponents = useCodeComponents({ codeActions });
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);

    // Stable components reference
    const components = useMemo(() => {
      return codeActions ? CodeComponents : undefined;
    }, [codeActions, CodeComponents]);

    return (
      <div className={combinedClassName}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={rehypePlugins}
          components={components}
        >
          {content}
        </ReactMarkdown>
      </div>
    );
  },
  // Custom comparison function for better memoization
  (prevProps, nextProps) => {
    return (
      prevProps.content === nextProps.content &&
      prevProps.className === nextProps.className &&
      prevProps.prose === nextProps.prose &&
      prevProps.codeActions === nextProps.codeActions
    );
  }
);

MarkdownContent.displayName = 'MarkdownContent';

export default MarkdownContent;
