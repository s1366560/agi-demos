/**
 * MarkdownContent - Unified Markdown rendering component
 *
 * Provides consistent Markdown rendering across the application with:
 * - GitHub Flavored Markdown (GFM) support (tables, strikethrough, task lists)
 * - Proper styling for links and images
 * - Syntax highlighting support (via prose classes)
 * - Code block actions (Copy, Open in Canvas)
 *
 * This component can be reused in:
 * - AssistantMessage
 * - ToolExecutionCardDisplay (for tool results)
 * - FinalResponseDisplay
 */

import { memo, useMemo } from 'react';

import ReactMarkdown from 'react-markdown';

import remarkGfm from 'remark-gfm';

import { CodeBlock } from './CodeBlock';

import type { Components } from 'react-markdown';

export interface MarkdownContentProps {
  /** Markdown content to render */
  content: string;
  /** Additional CSS classes for the container */
  className?: string;
  /** Whether to enable full prose styling */
  prose?: boolean;
  /** Whether to show code block actions (copy, open in canvas) */
  codeActions?: boolean;
}

// Hoist prose classes outside component to avoid recreation on each render
const PROSE_CLASSES =
  'prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-headings:mt-4 prose-headings:mb-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md';

const CODE_COMPONENTS: Components = {
  pre: ({ children, ...props }) => <CodeBlock {...props}>{children}</CodeBlock>,
};

/**
 * MarkdownContent component
 * Memoized to prevent re-renders when parent re-renders but content hasn't changed
 *
 * @example
 * // Full prose styling with code actions (for message content)
 * <MarkdownContent content="# Header\n\n```js\nconst x = 1;\n```" prose codeActions />
 *
 * @example
 * // Minimal styling (for inline or tool results)
 * <MarkdownContent content="**Result:** Done" className="text-xs" />
 */
export const MarkdownContent = memo<MarkdownContentProps>(
  ({ content, className = '', prose = true, codeActions = false }) => {
    const combinedClassName = prose ? `${PROSE_CLASSES} ${className}`.trim() : className;
    const components = useMemo(
      () => (codeActions ? CODE_COMPONENTS : undefined),
      [codeActions]
    );

    return (
      <div className={combinedClassName}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {content}
        </ReactMarkdown>
      </div>
    );
  }
);

MarkdownContent.displayName = 'MarkdownContent';

export default MarkdownContent;
