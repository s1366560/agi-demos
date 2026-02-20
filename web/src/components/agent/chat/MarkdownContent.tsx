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

import { memo, useMemo, lazy, Suspense } from 'react';

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
// Define the lazy component outside to prevent recreation
const LazyCodeBlock = lazy(() => import('./CodeBlock').then((module) => ({ default: module.CodeBlock })));

const CodeBlockWithSuspense: React.FC<{
  children?: React.ReactNode;
  codeActions?: boolean;
  loadingFallback?: React.ReactNode;
}> = ({ children, codeActions = false, loadingFallback }) => {
  return (
    <Suspense fallback={loadingFallback || <CodeBlockLoadingFallback />}>
      {/* @ts-ignore - Dynamic component props type check issue */}
      <LazyCodeBlock codeActions={codeActions}>{children}</LazyCodeBlock>
    </Suspense>
  );
};

/**
 * MarkdownContent component
 * 
 * Optimizations:
 * - React.memo prevents re-renders when props haven't changed
 * - Lazy loading for heavy components (CodeBlock)
 * - useMemo for plugin initialization
 */
export const MarkdownContent = memo<MarkdownContentProps>(
  ({ content, className = '', prose = true, codeActions = false, loadingFallback }) => {
    const combinedClassName = prose ? `${MARKDOWN_PROSE_CLASSES} ${className}`.trim() : className;
    
    // Stable components reference
    const components: Components = useMemo(() => {
      if (!codeActions) return {};
      
      return {
        pre: ({ children }) => (
          <CodeBlockWithSuspense codeActions={codeActions} loadingFallback={loadingFallback}>
            {children}
          </CodeBlockWithSuspense>
        ),
      };
    }, [codeActions, loadingFallback]);

    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);

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
      prevProps.codeActions === nextProps.codeActions &&
      prevProps.loadingFallback === nextProps.loadingFallback
    );
  }
);

MarkdownContent.displayName = 'MarkdownContent';

export default MarkdownContent;
