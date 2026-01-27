/**
 * MarkdownContent - Unified Markdown rendering component
 *
 * Provides consistent Markdown rendering across the application with:
 * - GitHub Flavored Markdown (GFM) support (tables, strikethrough, task lists)
 * - Proper styling for links and images
 * - Syntax highlighting support (via prose classes)
 *
 * This component can be reused in:
 * - AssistantMessage
 * - ToolExecutionCardDisplay (for tool results)
 * - FinalResponseDisplay
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export interface MarkdownContentProps {
  /** Markdown content to render */
  content: string;
  /** Additional CSS classes for the container */
  className?: string;
  /** Whether to enable full prose styling */
  prose?: boolean;
}

/**
 * MarkdownContent component
 *
 * @example
 * // Full prose styling (for message content)
 * <MarkdownContent content="# Header\n\n**Bold** text" prose={true} />
 *
 * @example
 * // Minimal styling (for inline or tool results)
 * <MarkdownContent content="**Result:** Done" className="text-xs" />
 */
export function MarkdownContent({
  content,
  className = '',
  prose = true,
}: MarkdownContentProps) {
  // Base prose classes for full markdown styling
  const proseClasses = prose
    ? 'prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-headings:mt-4 prose-headings:mb-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md'
    : '';

  return (
    <div className={`${proseClasses} ${className}`.trim()}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownContent;
