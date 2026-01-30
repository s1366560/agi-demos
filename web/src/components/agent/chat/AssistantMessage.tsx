/**
 * AssistantMessage - Unified assistant message renderer
 *
 * Renders assistant responses in two modes:
 * 1. Normal response: Simple bubble with ReactMarkdown rendering
 * 2. Report mode: Full FinalResponseDisplay with actions sidebar
 *
 * Mode is determined by message.metadata.isReport flag.
 *
 * Supports typewriter effect for streaming responses.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { FinalResponseDisplay } from './FinalResponseDisplay';

export interface AssistantMessageProps {
  /** Message content (markdown) */
  content: string;
  /** Whether to display as a formal report */
  isReport?: boolean;
  /** Generation timestamp */
  generatedAt?: string;
  /** Whether currently streaming (shows typing cursor) */
  isStreaming?: boolean;
}

/**
 * AssistantMessage component
 *
 * @example
 * // Normal response
 * <AssistantMessage content="Here is the information..." />
 *
 * @example
 * // Report mode
 * <AssistantMessage content="# Analysis Report..." isReport={true} />
 *
 * @example
 * // Streaming response with typewriter effect
 * <AssistantMessage content="Partial text..." isStreaming={true} />
 */
export function AssistantMessage({
  content,
  isReport = false,
  generatedAt,
  isStreaming = false,
}: AssistantMessageProps) {
  // Report mode: Use FinalResponseDisplay
  if (isReport) {
    return (
      <FinalResponseDisplay
        content={content}
        generatedAt={generatedAt}
        isStreaming={isStreaming}
      />
    );
  }

  // Normal response: Simple bubble with ReactMarkdown + GFM support
  return (
    <div className="flex items-start gap-3">
      {/* Robot avatar */}
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/20 to-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <span className="material-symbols-outlined text-primary text-lg">
          smart_toy
        </span>
      </div>

      {/* Message content bubble */}
      <div
        className="flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-5 prose prose-sm dark:prose-invert max-w-none prose-p:my-1.5 prose-headings:mt-3 prose-headings:mb-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none prose-a:text-primary prose-a:no-underline hover:prose-a:underline prose-th:text-left prose-img:rounded-lg prose-img:shadow-md leading-relaxed"
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}

export default AssistantMessage;
