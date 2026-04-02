/**
 * MessageArea - Modern message display area with aggressive preloading
 *
 * ## Usage
 *
 * ### Convenience Usage (Default rendering)
 * ```tsx
 * <MessageArea
 *   timeline={timeline}
 *   isStreaming={false}
 *   isLoading={false}
 * />
 * ```
 *
 * ### Compound Components (Custom rendering)
 * ```tsx
 * <MessageArea timeline={timeline} ...>
 *   <MessageArea.ScrollIndicator />
 *   <MessageArea.Content />
 *   <MessageArea.ScrollButton />
 * </MessageArea>
 * ```
 *
 * ## Features
 * - Aggressive preloading for seamless backward pagination
 * - Scroll position restoration without jumping
 * - Auto-scroll to bottom for new messages
 * - Scroll to bottom button when user scrolls up
 */

import {
  useRef,
  useEffect,
  useCallback,
  useState,
  memo,
  Children,
  useMemo,
  isValidElement,
  useId,
} from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';

import { useVirtualizer } from '@tanstack/react-virtual';
import { ChevronDown, ChevronUp, Loader2, Pin, PinOff } from 'lucide-react';

import { usePinnedEventIds, useAgentHITLStore } from '../../stores/agent/hitlStore';
import {
  useStreamingAssistantContent,
  useStreamingThought,
  useIsThinkingStreaming,
} from '../../stores/agent/streamingStore';

import { useMarkdownPlugins, safeMarkdownComponents } from './chat/markdownPlugins';
import { SuggestionChips } from './chat/SuggestionChips';
import { ThinkingBlock } from './chat/ThinkingBlock';
import { ConversationSummaryCardWrapper } from './message/ConversationSummaryCardWrapper';
import { groupTimelineEvents } from './message/groupTimelineEvents';
import { estimateGroupedItemHeight } from './message/heightEstimation';
import {
  MessageAreaContext,
  useMessageArea,
  LOADING_SYMBOL,
  EMPTY_SYMBOL,
  SCROLL_INDICATOR_SYMBOL,
  SCROLL_BUTTON_SYMBOL,
  CONTENT_SYMBOL,
  STREAMING_CONTENT_SYMBOL,
  LoadingMarker,
  EmptyMarker,
  ScrollIndicatorMarker,
  ScrollButtonMarker,
  ContentMarker,
  StreamingContentMarker,
} from './message/markers';
import { StreamingToolPreparation } from './message/StreamingToolPreparation';
import { useMessageAreaKeyboard } from './message/useMessageAreaKeyboard';
import { useMessageAreaScroll } from './message/useMessageAreaScroll';
import { MessageBubble } from './MessageBubble';
import {
  ASSISTANT_AVATAR_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  MARKDOWN_PROSE_CLASSES,
  MESSAGE_MAX_WIDTH_CLASSES,
  WIDE_MESSAGE_MAX_WIDTH_CLASSES,
} from './styles';
import { ExecutionTimeline } from './timeline/ExecutionTimeline';
import { MemoryRecalledStep, MemoryCapturedStep } from './timeline/MemoryRecalledStep';
import { SubAgentCostSummary } from './timeline/SubAgentCostSummary';
import { SubAgentTimeline } from './timeline/SubAgentTimeline';

import type { SubAgentGroup } from './timeline/SubAgentTimeline';
import type { TimelineEvent } from '../../types/agent';

// Import and re-export types from separate file
export type {
  MessageAreaRootProps,
  MessageAreaContextValue,
  MessageAreaLoadingProps,
  MessageAreaEmptyProps,
  MessageAreaScrollIndicatorProps,
  MessageAreaScrollButtonProps,
  MessageAreaContentProps,
  MessageAreaStreamingContentProps,
  MessageAreaCompound,
} from './message/types';

// Re-export useMessageArea for external consumers
export { useMessageArea };

// Define local type aliases to avoid TS6192 (unused imports)
// These reference the same types as exported above
interface _MessageAreaRootProps {
  timeline: TimelineEvent[];
  streamingContent?: string | undefined;
  streamingThought?: string | undefined;
  isStreaming: boolean;
  isThinkingStreaming?: boolean | undefined;
  isLoading: boolean;
  hasEarlierMessages?: boolean | undefined;
  onLoadEarlier?: (() => void) | undefined;
  isLoadingEarlier?: boolean | undefined;
  preloadItemCount?: number | undefined;
  conversationId?: string | null | undefined;
  suggestions?: string[] | undefined;
  onSuggestionSelect?: ((suggestion: string) => void) | undefined;
  children?: React.ReactNode | undefined;
}

interface _MessageAreaScrollState {
  showScrollButton: boolean;
  showLoadingIndicator: boolean;
  scrollToBottom: () => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

interface _MessageAreaContextValue {
  timeline: TimelineEvent[];
  streamingContent?: string | undefined;
  streamingThought?: string | undefined;
  isStreaming: boolean;
  isThinkingStreaming?: boolean | undefined;
  isLoading: boolean;
  hasEarlierMessages: boolean;
  onLoadEarlier?: (() => void) | undefined;
  isLoadingEarlier: boolean;
  preloadItemCount: number;
  conversationId?: string | null | undefined;
  scroll: _MessageAreaScrollState;
}

interface _MessageAreaLoadingProps {
  className?: string | undefined;
  message?: string | undefined;
}

interface _MessageAreaEmptyProps {
  className?: string | undefined;
  title?: string | undefined;
  subtitle?: string | undefined;
}

interface _MessageAreaScrollIndicatorProps {
  className?: string | undefined;
  label?: string | undefined;
}

interface _MessageAreaScrollButtonProps {
  className?: string | undefined;
  title?: string | undefined;
}

interface _MessageAreaContentProps {
  className?: string | undefined;
}

interface _MessageAreaStreamingContentProps {
  className?: string | undefined;
}

interface _MessageAreaCompound extends React.FC<_MessageAreaRootProps> {
  Provider: React.FC<{ children: React.ReactNode }>;
  Loading: React.FC<_MessageAreaLoadingProps>;
  Empty: React.FC<_MessageAreaEmptyProps>;
  ScrollIndicator: React.FC<_MessageAreaScrollIndicatorProps>;
  ScrollButton: React.FC<_MessageAreaScrollButtonProps>;
  Content: React.FC<_MessageAreaContentProps>;
  StreamingContent: React.FC<_MessageAreaStreamingContentProps>;
  Root: React.FC<_MessageAreaRootProps>;
}

// Helper type for marker components with symbol tags and displayName
type _SymbolTagged = Record<symbol, boolean> & { displayName?: string };

// ========================================
// Actual Sub-Component Implementations
// ========================================

// Internal Loading component
const InternalLoading: React.FC<
  _MessageAreaLoadingProps & { context: _MessageAreaContextValue }
> = ({ message, context }) => {
  if (!context.isLoading) return null;
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <Loader2 className="animate-spin text-4xl text-primary mb-4" size={16} />
        <p className="text-slate-500">{message || 'Loading conversation...'}</p>
      </div>
    </div>
  );
};

// Internal Empty component
const InternalEmpty: React.FC<_MessageAreaEmptyProps & { context: _MessageAreaContextValue }> = ({
  title,
  subtitle,
  context,
}) => {
  if (context.isLoading) return null;
  if (context.timeline.length > 0) return null;
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center text-slate-400">
        <p>{title || 'No messages yet'}</p>
        <p className="text-sm">{subtitle || 'Start a conversation to see messages here'}</p>
      </div>
    </div>
  );
};

// ========================================
// Main Component
// ========================================

const MessageAreaInner: React.FC<_MessageAreaRootProps> = memo(
  ({
    timeline,
    streamingContent: propStreamingContent,
    streamingThought: propStreamingThought,
    isStreaming,
    isThinkingStreaming: propIsThinkingStreaming,
    isLoading,
    hasEarlierMessages = false,
    onLoadEarlier,
    isLoadingEarlier: propIsLoadingEarlier = false,
    preloadItemCount = 10,
    conversationId,
    suggestions,
    onSuggestionSelect,
    children,
  }) => {
    // Subscribe to fast-changing streaming values directly from the store
    // to avoid re-rendering the parent AgentChatContent on every token.
const storeStreamingContent = useStreamingAssistantContent();
  const storeStreamingThought = useStreamingThought();
  const storeIsThinkingStreaming = useIsThinkingStreaming();

    const streamingContent = isStreaming
      ? (storeStreamingContent ?? propStreamingContent ?? '')
      : '';
    const streamingThought = storeStreamingThought ?? propStreamingThought ?? '';
    const isThinkingStreaming = storeIsThinkingStreaming ?? Boolean(propIsThinkingStreaming);

    const containerRef = useRef<HTMLDivElement>(null);
    const [pinnedCollapsed, setPinnedCollapsed] = useState(false);
    const pinnedSectionId = useId();
    const { t } = useTranslation();
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(streamingContent);

    // Memoize grouped timeline items to avoid re-grouping on every render
    const groupedItems = useMemo(() => groupTimelineEvents(timeline), [timeline]);

    const subagentGroups = useMemo(
      () =>
        groupedItems
          .filter(
            (item): item is { kind: 'subagent'; group: SubAgentGroup; startIndex: number } =>
              item.kind === 'subagent'
          )
          .map((item) => item.group),
      [groupedItems]
    );

    const lastTimelineGroupIndex = useMemo(() => {
      for (let i = groupedItems.length - 1; i >= 0; i--) {
        if (groupedItems[i]?.kind === 'timeline') return i;
      }
      return -1;
    }, [groupedItems]);

    const pinnedEventIds = usePinnedEventIds();
    const togglePinEvent = useAgentHITLStore((s) => s.togglePinEvent);

    const pinnedEvents = useMemo(
      () => timeline.filter((e) => e.id && pinnedEventIds.has(e.id)),
      [timeline, pinnedEventIds]
    );

    // Parse children to detect sub-components (memoized to avoid re-scanning on every render)
    const markerChildren = useMemo(() => {
      const arr = Children.toArray(children);
      const find = <P,>(sym: symbol): React.ReactElement<P> | undefined =>
        arr.find(
          (child): child is React.ReactElement<P> =>
            isValidElement(child) &&
            typeof child.type === 'function' &&
            (child.type as unknown as _SymbolTagged)[sym] === true
        );
      return {
        loadingChild: find<_MessageAreaLoadingProps>(LOADING_SYMBOL),
        emptyChild: find<_MessageAreaEmptyProps>(EMPTY_SYMBOL),
        scrollIndicatorChild: find<_MessageAreaScrollIndicatorProps>(SCROLL_INDICATOR_SYMBOL),
        scrollButtonChild: find<_MessageAreaScrollButtonProps>(SCROLL_BUTTON_SYMBOL),
        contentChild: find<_MessageAreaContentProps>(CONTENT_SYMBOL),
        streamingContentChild: find<_MessageAreaStreamingContentProps>(STREAMING_CONTENT_SYMBOL),
      };
    }, [children]);
    const {
      loadingChild,
      emptyChild,
      scrollIndicatorChild,
      scrollButtonChild,
      contentChild,
      streamingContentChild,
    } = markerChildren;

    // Determine if using compound mode
    const hasSubComponents =
      loadingChild ||
      emptyChild ||
      scrollIndicatorChild ||
      scrollButtonChild ||
      contentChild ||
      streamingContentChild;

    // In legacy mode, include all sections by default
    // In compound mode, only include explicitly specified sections
    const includeLoading = hasSubComponents ? !!loadingChild : true;
    const includeEmpty = hasSubComponents ? !!emptyChild : true;
    const includeScrollIndicator = hasSubComponents ? !!scrollIndicatorChild : true;
    const includeScrollButton = hasSubComponents ? !!scrollButtonChild : true;
    const includeContent = hasSubComponents ? !!contentChild : true;
    const includeStreamingContent = hasSubComponents ? !!streamingContentChild : true;

    // Scroll management and pagination (extracted to useMessageAreaScroll)
    const {
      showScrollButton,
      showLoadingIndicator,
      scrollToBottom,
      handleScroll,
      isInitialLoadRef,
      hasScrolledInitiallyRef,
      prevTimelineLengthRef,
      previousScrollHeightRef,
      previousScrollTopRef,
      isLoadingEarlierRef,
      userScrolledUpRef,
      isSwitchingConversationRef,
      isPositioningRef,
      lastConversationIdRef,
    } = useMessageAreaScroll({
      containerRef,
      timeline,
      isStreaming,
      isThinkingStreaming,
      isLoading,
      streamingContent,
      streamingThought,
      hasEarlierMessages,
      onLoadEarlier,
      propIsLoadingEarlier,
      preloadItemCount,
    });

    const scrollState = useMemo(
      () => ({
        showScrollButton,
        showLoadingIndicator,
        scrollToBottom,
        containerRef,
      }),
      [showScrollButton, showLoadingIndicator, scrollToBottom]
    );

    const contextValue: _MessageAreaContextValue = useMemo(
      () => ({
        timeline,
        streamingContent,
        streamingThought,
        isStreaming,
        isThinkingStreaming,
        isLoading,
        hasEarlierMessages,
        onLoadEarlier,
        isLoadingEarlier: propIsLoadingEarlier,
        preloadItemCount,
        conversationId,
        scroll: scrollState,
      }),
      [
        timeline,
        streamingContent,
        streamingThought,
        isStreaming,
        isThinkingStreaming,
        isLoading,
        hasEarlierMessages,
        onLoadEarlier,
        propIsLoadingEarlier,
        preloadItemCount,
        conversationId,
        scrollState,
      ]
    );

    // Determine states
    const shouldShowLoading =
      (propIsLoadingEarlier && hasEarlierMessages) || (showLoadingIndicator && hasEarlierMessages);
    const showLoadingState = isLoading && timeline.length === 0;
    const showEmptyState = !isLoading && timeline.length === 0;

    const timelineLen = timeline.length;
    const lastEventIndex = timelineLen - 1;
    const hasStreamingThought = streamingThought.trim().length > 0;
    const hasStreamingText = streamingContent.trim().length > 0;
    const effectiveIsThinkingStreaming = isThinkingStreaming && !hasStreamingText;
    const shouldShowThinkingBlock =
      includeStreamingContent &&
      isStreaming &&
      (effectiveIsThinkingStreaming || (hasStreamingThought && !hasStreamingText));

    // Virtualizer setup
    const estimateSize = useCallback(
      (index: number) => {
        const item = groupedItems[index];
        return item ? estimateGroupedItemHeight(item) : 80;
      },
      [groupedItems]
    );

    const virtualizer = useVirtualizer({
      count: groupedItems.length,
      getScrollElement: () => containerRef.current,
      estimateSize,
      overscan: 15,
      paddingEnd: isStreaming ? 16 : 0,
    });

    // biome-ignore lint/correctness/useExhaustiveDependencies: refs from useMessageAreaScroll are stable MutableRefObject references that never change identity
    useEffect(() => {
      if (lastConversationIdRef.current === conversationId) return;
      lastConversationIdRef.current = conversationId;

      isSwitchingConversationRef.current = true;
      isPositioningRef.current = true;

      isInitialLoadRef.current = true;
      hasScrolledInitiallyRef.current = false;
      prevTimelineLengthRef.current = 0;
      previousScrollHeightRef.current = 0;
      previousScrollTopRef.current = 0;
      isLoadingEarlierRef.current = false;
      userScrolledUpRef.current = false;

      // Reset virtualizer measurements so stale sizes don't cause jumps.
      virtualizer.measure();

      // Double-rAF: first frame lets virtualizer re-measure visible items,
      // second frame scrolls after layout has settled.
      const rafId = requestAnimationFrame(() => {
        const rafId2 = requestAnimationFrame(() => {
          if (groupedItems.length > 0) {
            virtualizer.scrollToIndex(groupedItems.length - 1, { align: 'end' });
            isInitialLoadRef.current = false;
            hasScrolledInitiallyRef.current = true;
            prevTimelineLengthRef.current = timeline.length;
          }
          // Always clear switching flag so timeline-change effect can handle
          // the scroll if data arrives later.
          isSwitchingConversationRef.current = false;
          // Release positioning guard after one more frame for layout to settle
          requestAnimationFrame(() => {
            isPositioningRef.current = false;
          });
        });
        cleanupRef.current = rafId2;
      });
      // Store inner rAF id for cleanup
      const cleanupRef = { current: 0 as number };

      return () => {
        cancelAnimationFrame(rafId);
        if (cleanupRef.current) cancelAnimationFrame(cleanupRef.current);
      };
    }, [conversationId, virtualizer, groupedItems.length, timeline.length]);

    // Keyboard navigation (extracted to useMessageAreaKeyboard)
    const { focusedMsgIndex } = useMessageAreaKeyboard({
      containerRef,
      groupedItems,
    });

    return (
      <MessageAreaContext.Provider value={contextValue}>
        <div className="h-full w-full relative flex flex-col overflow-hidden">
          {/* Loading state */}
          {includeLoading && showLoadingState && (
            <InternalLoading context={contextValue} {...loadingChild?.props} />
          )}

          {/* Empty state */}
          {includeEmpty && showEmptyState && (
            <InternalEmpty context={contextValue} {...emptyChild?.props} />
          )}

          {/* Scroll indicator for earlier messages */}
          {includeScrollIndicator && shouldShowLoading && (
            <div
              className="absolute top-2 left-0 right-0 z-10 flex justify-center pointer-events-none"
              data-testid="scroll-indicator"
            >
              <div className="flex items-center px-3 py-1.5 bg-slate-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-full shadow-sm border border-slate-200/50 dark:border-slate-700/50 opacity-70">
                <Loader2 className="animate-spin text-primary mr-2" size={16} />
                <span className="text-xs text-slate-500">
                  {scrollIndicatorChild?.props.label || 'Loading...'}
                </span>
              </div>
            </div>
          )}

          {/* Pinned Messages Section */}
          {pinnedEvents.length > 0 && (
            <div className="flex-shrink-0 border-b border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/50">
              <button
                type="button"
                onClick={() => {
                  setPinnedCollapsed(!pinnedCollapsed);
                }}
                aria-expanded={!pinnedCollapsed}
                aria-controls={pinnedSectionId}
                className="flex items-center gap-2 w-full px-4 py-2 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700/50 active:bg-slate-200 dark:active:bg-slate-700/70 transition-colors duration-150 motion-reduce:transition-none min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
              >
                <Pin size={12} />
                <span>{t('agent.pinnedMessages', 'Pinned')}</span>
                <span className="text-slate-400">({pinnedEvents.length})</span>
                <span className="ml-auto">
                  {pinnedCollapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
                </span>
              </button>
              {!pinnedCollapsed && (
                <div
                  id={pinnedSectionId}
                  className="px-4 pb-2 space-y-1.5 max-h-40 overflow-y-auto"
                >
                  {pinnedEvents.map((event) => {
                    const content =
                      ('content' in event ? (event as { content: string }).content : '') ||
                      ('fullText' in event ? (event as { fullText: string }).fullText : '');
                    return (
                      <div
                        key={`pinned-${event.id}`}
                        className="flex items-start gap-2 px-3 py-2 bg-white dark:bg-slate-800 rounded-lg border border-slate-200/80 dark:border-slate-700/50 transition-colors group/pin hover:bg-slate-100 dark:hover:bg-slate-700/60"
                      >
                        <button
                          type="button"
                          onClick={() => {
                            const targetId = event.id;
                            const el = Array.from(
                              containerRef.current?.querySelectorAll<HTMLElement>(
                                '[data-msg-id]'
                              ) ?? []
                            ).find((node) => node.getAttribute('data-msg-id') === targetId);
                            if (el) {
                              el.scrollIntoView({
                                block: 'center',
                                behavior: window.matchMedia('(prefers-reduced-motion: reduce)')
                                  .matches
                                  ? 'auto'
                                  : 'smooth',
                              });
                            }
                          }}
                          className="flex-1 min-w-0 text-left rounded-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                          aria-label={t('agent.actions.jumpToMessage', 'Jump to message')}
                        >
                          <p className="text-xs text-slate-600 dark:text-slate-300 line-clamp-2 leading-relaxed">
                            {content || '...'}
                          </p>
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (event.id) togglePinEvent(event.id);
                          }}
                          className="touch-target flex-shrink-0 p-1.5 rounded text-slate-400 hover:text-red-500 active:text-red-600 opacity-100 md:opacity-0 md:group-hover/pin:opacity-100 md:group-focus-within/pin:opacity-100 transition-all duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
                          aria-label={t('agent.actions.unpin', 'Unpin')}
                        >
                          <PinOff size={12} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Message Container with Content */}
          {includeContent && !showLoadingState && !showEmptyState && (
            <div
              ref={containerRef}
              onScroll={handleScroll}
              className="flex-1 overflow-y-auto chat-scrollbar p-3 md:p-4 pb-20 min-h-0"
              data-testid="message-container"
              role="log"
              aria-live="polite"
            >
              <ConversationSummaryCardWrapper conversationId={conversationId} />
              {/* Virtualized message list */}
              <div
                style={{
                  height: virtualizer.getTotalSize(),
                  width: '100%',
                  position: 'relative',
                }}
              >
                {virtualizer.getVirtualItems().map((virtualRow) => {
                  const item = groupedItems[virtualRow.index];
                  if (!item) return null;
                  if (item.kind === 'timeline') {
                    return (
                      <div
                        key={`timeline-group-${String(item.startIndex)}`}
                        data-index={virtualRow.index}
                        data-msg-index={virtualRow.index}
                        ref={virtualizer.measureElement}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${String(virtualRow.start)}px)`,
                        }}
                      >
                        <div className="flex items-start gap-3 pb-1">
                          <div className="w-8 shrink-0" />
                          <div className={`flex-1 min-w-0 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
                            <ExecutionTimeline
                              steps={item.steps}
                              isStreaming={
                                isStreaming && item.startIndex + item.steps.length >= timelineLen
                              }
                              defaultCollapsed={virtualRow.index !== lastTimelineGroupIndex}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  }
                  if (item.kind === 'subagent') {
                    return (
                      <div
                        key={`subagent-group-${String(item.startIndex)}`}
                        data-index={virtualRow.index}
                        data-msg-index={virtualRow.index}
                        data-timeline-index={item.startIndex}
                        data-subagent-start-index={item.startIndex}
                        data-subagent-id={item.group.subagentId}
                        ref={virtualizer.measureElement}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${String(virtualRow.start)}px)`,
                        }}
                      >
                        <div className="flex items-start gap-3 pb-1">
                          <div className="w-8 shrink-0" />
                          <div className={`flex-1 min-w-0 ${WIDE_MESSAGE_MAX_WIDTH_CLASSES}`}>
                            <SubAgentTimeline
                              group={item.group}
                              isStreaming={
                                isStreaming &&
                                item.startIndex + item.group.events.length >= timelineLen
                              }
                            />
                          </div>
                        </div>
                      </div>
                    );
                  }
                  const { event, index } = item;

                  // Memory events: render as compact timeline steps
                  if (event.type === 'memory_recalled' || event.type === 'memory_captured') {
                    return (
                      <div
                        key={event.id || `event-${String(index)}`}
                        data-index={virtualRow.index}
                        ref={virtualizer.measureElement}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${String(virtualRow.start)}px)`,
                        }}
                      >
                        <div className="flex items-start gap-3 pb-1">
                          <div className="w-8 shrink-0" />
                          <div className={`flex-1 min-w-0 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
                            {event.type === 'memory_recalled' ? (
                              <MemoryRecalledStep event={event} />
                            ) : (
                              <MemoryCapturedStep event={event} />
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  }

                  const isFocused = focusedMsgIndex === virtualRow.index;
                  return (
                    <div
                      key={event.id || `event-${String(index)}`}
                      data-index={virtualRow.index}
                      data-msg-index={virtualRow.index}
                      data-msg-id={event.id}
                      ref={virtualizer.measureElement}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${String(virtualRow.start)}px)`,
                      }}
                      className={
                        isFocused
                          ? 'ring-2 ring-blue-400/60 dark:ring-blue-500/50 rounded-xl transition-shadow duration-200'
                          : ''
                      }
                    >
                      <div className="pb-1">
                        <MessageBubble
                          event={event}
                          isStreaming={isStreaming && index === lastEventIndex}
                          allEvents={timeline}
                          isPinned={!!event.id && pinnedEventIds.has(event.id)}
                          onPin={
                            event.id
                              ? () => {
                                  togglePinEvent(event.id);
                                }
                              : undefined
                          }
                        />
                      </div>
                    </div>
                  );
                })}
              </div>

              {subagentGroups.length >= 2 && !isStreaming && (
                <div
                  className="flex items-start gap-3 pb-3"
                  style={{ marginTop: virtualizer.getTotalSize() ? 8 : 0 }}
                >
                  <div className="w-8 shrink-0" />
                  <div className={`flex-1 min-w-0 ${MESSAGE_MAX_WIDTH_CLASSES}`}>
                    <SubAgentCostSummary groups={subagentGroups} />
                  </div>
                </div>
              )}

              {/* Non-virtualized streaming/footer content */}
              <div className="space-y-1.5">
                {/* Suggestion chips - shown when not streaming and suggestions available */}
                {!isStreaming && suggestions && suggestions.length > 0 && onSuggestionSelect && (
                  <SuggestionChips suggestions={suggestions} onSelect={onSuggestionSelect} />
                )}

                {/* Streaming thought indicator - ThinkingBlock (new design) */}
                {shouldShowThinkingBlock && (
                  <ThinkingBlock
                    content={streamingThought || ''}
                    isStreaming={effectiveIsThinkingStreaming}
                  />
                )}

                {/* Streaming tool preparation indicator */}
                {includeStreamingContent && isStreaming && <StreamingToolPreparation />}

                {/* Streaming content indicator - matches MessageBubble.Assistant style */}
                {includeStreamingContent &&
                  isStreaming &&
                  streamingContent &&
                  !effectiveIsThinkingStreaming && (
                    <div
                      className="flex items-start gap-3 mb-2 animate-fade-in-up"
                      aria-live="assertive"
                    >
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
              </div>
            </div>
          )}

          {/* Scroll to bottom button */}
          {includeScrollButton && showScrollButton && (
            <button
              onClick={contextValue.scroll.scrollToBottom}
              className="touch-target absolute bottom-6 right-6 z-10 flex items-center justify-center w-11 h-11 rounded-full bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 shadow-md border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 hover:shadow-lg transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-150 animate-fade-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
              title={scrollButtonChild?.props.title || 'Scroll to bottom'}
              aria-label="Scroll to bottom"
              data-testid="scroll-button"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 14l-7 7m0 0l-7-7m7 7V3"
                />
              </svg>
            </button>
          )}
        </div>
      </MessageAreaContext.Provider>
    );
  }
);

MessageAreaInner.displayName = 'MessageAreaInner';

// Create compound component with sub-components
const MessageAreaMemo = memo(MessageAreaInner);
MessageAreaMemo.displayName = 'MessageArea';

// Create compound component object
const MessageAreaCompound = MessageAreaMemo as unknown as _MessageAreaCompound;
MessageAreaCompound.Provider = ({ children }: { children: React.ReactNode }) => (
  <MessageAreaContext.Provider value={null}>{children}</MessageAreaContext.Provider>
);
MessageAreaCompound.Loading = LoadingMarker;
MessageAreaCompound.Empty = EmptyMarker;
MessageAreaCompound.ScrollIndicator = ScrollIndicatorMarker;
MessageAreaCompound.ScrollButton = ScrollButtonMarker;
MessageAreaCompound.Content = ContentMarker;
MessageAreaCompound.StreamingContent = StreamingContentMarker;
MessageAreaCompound.Root = MessageAreaMemo;

// Export compound component
export const MessageArea = MessageAreaCompound;

export default MessageArea;
