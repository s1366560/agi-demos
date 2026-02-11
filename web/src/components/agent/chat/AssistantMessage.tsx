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

import {
  MARKDOWN_PROSE_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  ASSISTANT_AVATAR_CLASSES,
} from '../styles';

import { CodeBlock } from './CodeBlock';
import { FinalResponseDisplay } from './FinalResponseDisplay';

import type { Components } from 'react-markdown';

const MARKDOWN_COMPONENTS: Components = {
  pre: ({ children, ...props }) => <CodeBlock {...props}>{children}</CodeBlock>,
};

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
      <FinalResponseDisplay content={content} generatedAt={generatedAt} isStreaming={isStreaming} />
    );
  }

  // Normal response: Simple bubble with ReactMarkdown + GFM support
  return (
    <div className="flex items-start gap-3">
      {/* Robot avatar */}
      <div className={ASSISTANT_AVATAR_CLASSES}>
        <span className="material-symbols-outlined text-primary text-lg">smart_toy</span>
      </div>

      {/* Message content bubble */}
      <div className={`${ASSISTANT_BUBBLE_CLASSES} p-5 ${MARKDOWN_PROSE_CLASSES}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}

export default AssistantMessage;
