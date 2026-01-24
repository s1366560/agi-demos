/**
 * AssistantMessage - Unified assistant message renderer
 *
 * Renders assistant responses in two modes:
 * 1. Normal response: Simple bubble with ReactMarkdown rendering
 * 2. Report mode: Full FinalResponseDisplay with actions sidebar
 *
 * Mode is determined by message.metadata.isReport flag.
 */

import ReactMarkdown from 'react-markdown';
import { FinalResponseDisplay } from './FinalResponseDisplay';

export interface AssistantMessageProps {
  /** Message content (markdown) */
  content: string;
  /** Whether to display as a formal report */
  isReport?: boolean;
  /** Generation timestamp */
  generatedAt?: string;
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
 */
export function AssistantMessage({
  content,
  isReport = false,
  generatedAt,
}: AssistantMessageProps) {
  // Report mode: Use FinalResponseDisplay
  if (isReport) {
    return (
      <FinalResponseDisplay
        content={content}
        generatedAt={generatedAt}
      />
    );
  }

  // Normal response: Simple bubble with ReactMarkdown
  return (
    <div className="flex items-start gap-3">
      {/* Robot avatar */}
      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-1">
        <span className="material-symbols-outlined text-primary text-lg">
          smart_toy
        </span>
      </div>

      {/* Message content bubble */}
      <div className="flex-1 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none shadow-sm p-4 prose prose-sm dark:prose-invert max-w-none prose-p:my-2 prose-headings:mt-4 prose-headings:mb-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-pre:bg-slate-100 prose-pre:dark:bg-slate-800 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

export default AssistantMessage;
