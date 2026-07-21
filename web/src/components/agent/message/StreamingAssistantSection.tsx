/**
 * StreamingAssistantSection - Live streaming indicator for MessageArea
 *
 * Subscribes to the fast-changing streaming stores (assistant content,
 * thought, thinking flag) in this leaf component so that per-flush token
 * updates (every ~50ms) re-render only this section instead of the entire
 * message area (virtualized list, timelines, grouped items).
 *
 * Also owns the scroll-follow behavior while content streams in.
 */

import { memo, useEffect } from 'react';

import ReactMarkdown from 'react-markdown';

import {
  useStreamingAssistantContent,
  useStreamingThought,
  useIsThinkingStreaming,
} from '../../../stores/agent/streamingStore';
import { useMarkdownPlugins } from '../chat/markdownPlugins';
import { safeMarkdownComponents } from '../chat/safeMarkdownComponents';
import { ThinkingBlock } from '../chat/ThinkingBlock';
import {
  ASSISTANT_AVATAR_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  MARKDOWN_PROSE_CLASSES,
  MESSAGE_MAX_WIDTH_CLASSES,
} from '../styles';

import { StreamingToolPreparation } from './StreamingToolPreparation';

export interface StreamingAssistantSectionProps {
  /** Scroll container owning the message list */
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** Whether the user manually scrolled up (suppresses scroll-follow) */
  userScrolledUpRef: React.RefObject<boolean>;
  /** Conversation-switch flag cleared when new content streams in */
  isSwitchingConversationRef: React.RefObject<boolean>;
}

export const StreamingAssistantSection: React.FC<StreamingAssistantSectionProps> = memo(
  ({ containerRef, userScrolledUpRef, isSwitchingConversationRef }) => {
    const streamingContent = useStreamingAssistantContent();
    const streamingThought = useStreamingThought();
    const isThinkingStreaming = useIsThinkingStreaming();
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(streamingContent);

    const hasStreamingThought = streamingThought.trim().length > 0;
    const hasStreamingText = streamingContent.trim().length > 0;
    const effectiveIsThinkingStreaming = isThinkingStreaming && !hasStreamingText;
    const shouldShowThinkingBlock =
      effectiveIsThinkingStreaming || (hasStreamingThought && !hasStreamingText);

    // Keep the scroll pinned to the bottom while new content streams in.
    // streamingContent/streamingThought are intentional trigger deps.
    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      const hasContent = streamingContent.trim().length > 0;
      const hasThought = streamingThought.trim().length > 0;
      const thoughtOnlyStreaming = isThinkingStreaming && hasThought && !hasContent;

      if (!userScrolledUpRef.current && !thoughtOnlyStreaming) {
        isSwitchingConversationRef.current = false;

        requestAnimationFrame(() => {
          if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
          }
        });
      }
    }, [
      streamingContent,
      streamingThought,
      isThinkingStreaming,
      containerRef,
      userScrolledUpRef,
      isSwitchingConversationRef,
    ]);

    return (
      <>
        {/* Streaming thought indicator - ThinkingBlock (new design) */}
        {shouldShowThinkingBlock && (
          <ThinkingBlock
            content={streamingThought || ''}
            isStreaming={effectiveIsThinkingStreaming}
          />
        )}

        {/* Streaming tool preparation indicator */}
        <StreamingToolPreparation />

        {/* Streaming content indicator - matches MessageBubble.Assistant style */}
        {streamingContent && !effectiveIsThinkingStreaming && (
          <div className="flex items-start gap-3 mb-2 animate-fade-in-up" aria-live="off">
            <div className={ASSISTANT_AVATAR_CLASSES}>
              <svg
                className="w-4.5 h-4.5 text-primary"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"
                />
              </svg>
            </div>
            <div className={`flex-1 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
              <div className={ASSISTANT_BUBBLE_CLASSES}>
                <div className={MARKDOWN_PROSE_CLASSES}>
                  <ReactMarkdown
                    remarkPlugins={remarkPlugins}
                    rehypePlugins={rehypePlugins}
                    components={safeMarkdownComponents}
                  >
                    {streamingContent}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }
);

StreamingAssistantSection.displayName = 'StreamingAssistantSection';
