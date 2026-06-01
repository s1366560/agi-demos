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
import { applyTurnCollapse, computeTurns, isTurnPlaceholder } from './message/turnFolding';
import { TurnPlaceholderRow } from './message/TurnPlaceholderRow';
import { useMessageAreaKeyboard } from './message/useMessageAreaKeyboard';
import { useMessageAreaScroll } from './message/useMessageAreaScroll';
import { useTurnCollapse } from './message/useTurnCollapse';
import { MessageBubble } from './MessageBubble';
import {
  ASSISTANT_AVATAR_CLASSES,
  ASSISTANT_BUBBLE_CLASSES,
  MARKDOWN_PROSE_CLASSES,
  MESSAGE_MAX_WIDTH_CLASSES,
  WIDE_MESSAGE_MAX_WIDTH_CLASSES,
} from './styles';
import { ExecutionTimeline } from './timeline/ExecutionTimeline';
import { JitContextCard } from './timeline/JitContextCard';
import { MemoryCapturedStep } from './timeline/MemoryRecalledStep';
import { SubAgentTimeline } from './timeline/SubAgentTimeline';

import type { DisplayItem } from './message/turnFolding';
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

// Re-export useMessageArea for external consumers.
// eslint-disable-next-line react-refresh/only-export-components
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
  onAgentSessionSelect?: ((sessionId: string) => void) | undefined;
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

const getTextSize = (value: unknown): number => {
  if (typeof value === 'string') return value.length;
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value).length;
  try {
    return JSON.stringify(value).length;
  } catch {
    return 0;
  }
};

const getDisplayItemKey = (item: DisplayItem, index: number): string => {
  if (item.kind === 'turn-placeholder') {
    return `turn-placeholder:${item.turnId}:${String(item.hiddenCount)}:${String(item.startIndex)}-${String(item.endIndex)}`;
  }

  if (item.kind === 'timeline') {
    const firstStep = item.steps[0];
    return ['timeline', String(item.startIndex), firstStep?.id ?? 'first'].join(':');
  }

  if (item.kind === 'subagent') {
    return [
      'subagent',
      item.group.subagentId || String(item.startIndex),
      String(item.startIndex),
    ].join(':');
  }

  return item.event.id || `event:${item.event.type}:${String(index)}`;
};

const getDisplayItemMeasurementKey = (item: DisplayItem, index: number): string => {
  const baseKey = getDisplayItemKey(item, index);

  if (item.kind === 'timeline') {
    const sizeSignature = item.steps
      .map((step) =>
        [
          step.id,
          step.status,
          String(getTextSize(step.input)),
          String(getTextSize(step.output)),
          String(step.duration ?? ''),
        ].join('/')
      )
      .join('|');
    return `${baseKey}:${sizeSignature}`;
  }

  if (item.kind === 'subagent') {
    return [
      baseKey,
      item.group.summary?.length ?? 0,
      item.group.error?.length ?? 0,
      item.group.task?.length ?? 0,
    ].join(':');
  }

  if (item.kind === 'event') {
    const event = item.event as TimelineEvent & {
      content?: string | undefined;
      fullText?: string | undefined;
    };
    return `${baseKey}:${String(event.content?.length ?? 0)}:${String(event.fullText?.length ?? 0)}`;
  }

  return baseKey;
};

// ========================================
// Actual Sub-Component Implementations
// ========================================

// Internal Loading component
const InternalLoading: React.FC<
  _MessageAreaLoadingProps & { context: _MessageAreaContextValue }
> = ({ message, context }) => {
  const { t } = useTranslation();

  if (!context.isLoading) return null;
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <Loader2 className="animate-spin text-4xl text-primary mb-4" size={16} />
        <p className="text-slate-500">
          {message ||
            t('components.messageArea.loadingConversation', {
              defaultValue: 'Loading conversation...',
            })}
        </p>
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
  const { t } = useTranslation();

  if (context.isLoading) return null;
  if (context.timeline.length > 0) return null;
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center text-slate-400">
        <p>
          {title || t('components.messageArea.emptyTitle', { defaultValue: 'No messages yet' })}
        </p>
        <p className="text-sm">
          {subtitle ||
            t('components.messageArea.emptySubtitle', {
              defaultValue: 'Start a conversation to see messages here',
            })}
        </p>
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
    isStreaming,
    isLoading,
    hasEarlierMessages = false,
    onLoadEarlier,
    isLoadingEarlier: propIsLoadingEarlier = false,
    preloadItemCount = 10,
    conversationId,
    suggestions,
    onSuggestionSelect,
    onAgentSessionSelect,
    children,
  }) => {
    // Subscribe to fast-changing streaming values directly from the store
    // to avoid re-rendering the parent AgentChatContent on every token.
    const storeStreamingContent = useStreamingAssistantContent();
    const storeStreamingThought = useStreamingThought();
    const storeIsThinkingStreaming = useIsThinkingStreaming();

    const streamingContent = isStreaming ? storeStreamingContent : '';
    const streamingThought = storeStreamingThought;
    const isThinkingStreaming = storeIsThinkingStreaming;

    const containerRef = useRef<HTMLDivElement>(null);
    const [pinnedCollapsed, setPinnedCollapsed] = useState(false);
    const pinnedSectionId = useId();
    const { t } = useTranslation();
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(streamingContent);

    // Memoize grouped timeline items to avoid re-grouping on every render
    const groupedItems = useMemo(() => groupTimelineEvents(timeline), [timeline]);

    // Per-conversation collapsed turns (persisted in localStorage)
    const turnCollapse = useTurnCollapse(conversationId);
    const turns = useMemo(() => computeTurns(groupedItems), [groupedItems]);
    const displayItems = useMemo(
      () => applyTurnCollapse(groupedItems, turnCollapse.collapsed),
      [groupedItems, turnCollapse.collapsed]
    );
    const displayItemKeys = useMemo(
      () => displayItems.map((item, index) => getDisplayItemKey(item, index)),
      [displayItems]
    );
    const displayMeasurementKey = useMemo(
      () =>
        displayItems.map((item, index) => getDisplayItemMeasurementKey(item, index)).join('\u001f'),
      [displayItems]
    );

    // Map each grouped item index to the turn that owns it. Used to wire the
    // "collapse turn" button on user-message bubbles.
    const turnByUserMessageId = useMemo(() => {
      const map = new Map<string, (typeof turns)[number]>();
      for (const turn of turns) {
        if (turn.userIndex === -1) continue;
        const userItem = groupedItems[turn.userIndex];
        if (userItem && userItem.kind === 'event' && userItem.event.id) {
          map.set(userItem.event.id, turn);
        }
      }
      return map;
    }, [turns, groupedItems]);

    const lastTimelineGroupIndex = useMemo(() => {
      for (let i = displayItems.length - 1; i >= 0; i--) {
        if (displayItems[i]?.kind === 'timeline') return i;
      }
      return -1;
    }, [displayItems]);

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
        const item = displayItems[index];
        return item ? estimateGroupedItemHeight(item) : 80;
      },
      [displayItems]
    );
    const getItemKey = useCallback(
      (index: number) => displayItemKeys[index] ?? `missing:${String(index)}`,
      [displayItemKeys]
    );

    // eslint-disable-next-line react-hooks/incompatible-library
    const virtualizer = useVirtualizer({
      count: displayItems.length,
      getScrollElement: () => containerRef.current,
      estimateSize,
      getItemKey,
      overscan: 15,
      paddingEnd: isStreaming ? 16 : 0,
    });
    const virtualizerRef = useRef(virtualizer);
    const rowResizeObserverRef = useRef<ResizeObserver | null>(null);
    const rowElementsByKeyRef = useRef(new Map<string, Element>());
    const pendingMeasuredRowsRef = useRef(new Set<Element>());
    const rowMeasurementFrameRef = useRef<number | null>(null);

    virtualizerRef.current = virtualizer;

    const flushMeasuredRows = useCallback(() => {
      rowMeasurementFrameRef.current = null;
      const rows = Array.from(pendingMeasuredRowsRef.current);
      pendingMeasuredRowsRef.current.clear();

      for (const row of rows) {
        virtualizerRef.current.measureElement(row);
      }
    }, []);

    const scheduleRowMeasure = useCallback(
      (row: Element) => {
        pendingMeasuredRowsRef.current.add(row);
        if (rowMeasurementFrameRef.current !== null) return;
        rowMeasurementFrameRef.current = requestAnimationFrame(flushMeasuredRows);
      },
      [flushMeasuredRows]
    );

    const measureVirtualRow = useCallback(
      (rowKey: string, node: HTMLDivElement | null) => {
        const previousNode = rowElementsByKeyRef.current.get(rowKey);
        if (previousNode && previousNode !== node) {
          rowResizeObserverRef.current?.unobserve(previousNode);
          pendingMeasuredRowsRef.current.delete(previousNode);
          rowElementsByKeyRef.current.delete(rowKey);
        }

        if (!node) return;

        virtualizerRef.current.measureElement(node);

        if (typeof ResizeObserver === 'undefined') return;

        if (!rowResizeObserverRef.current) {
          rowResizeObserverRef.current = new ResizeObserver((entries) => {
            for (const entry of entries) {
              scheduleRowMeasure(entry.target);
            }
          });
        }

        if (previousNode !== node) {
          rowElementsByKeyRef.current.set(rowKey, node);
          rowResizeObserverRef.current.observe(node);
        }
      },
      [scheduleRowMeasure]
    );

    useEffect(() => {
      const pendingRows = pendingMeasuredRowsRef.current;
      const rowElements = rowElementsByKeyRef.current;
      return () => {
        rowResizeObserverRef.current?.disconnect();
        rowElements.clear();
        pendingRows.clear();
        if (rowMeasurementFrameRef.current !== null) {
          cancelAnimationFrame(rowMeasurementFrameRef.current);
          rowMeasurementFrameRef.current = null;
        }
      };
    }, []);

    useEffect(() => {
      virtualizerRef.current.measure();
    }, [displayMeasurementKey]);

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
          if (displayItems.length > 0) {
            virtualizer.scrollToIndex(displayItems.length - 1, { align: 'end' });
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
    }, [
      conversationId,
      virtualizer,
      displayItems.length,
      timeline.length,
      lastConversationIdRef,
      isSwitchingConversationRef,
      isPositioningRef,
      isInitialLoadRef,
      hasScrolledInitiallyRef,
      prevTimelineLengthRef,
      previousScrollHeightRef,
      previousScrollTopRef,
      isLoadingEarlierRef,
      userScrolledUpRef,
    ]);

    // Keyboard navigation (extracted to useMessageAreaKeyboard)
    const { focusedMsgIndex } = useMessageAreaKeyboard({
      containerRef,
      groupedItems: displayItems,
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
              <div className="flex items-center px-3 py-1.5 bg-slate-100 dark:bg-slate-800 rounded-lg shadow-sm border border-slate-200/70 dark:border-slate-700/70 opacity-80">
                <Loader2 className="animate-spin text-primary mr-2" size={16} />
                <span className="text-xs text-slate-500">
                  {scrollIndicatorChild?.props.label ||
                    t('components.messageArea.loading', { defaultValue: 'Loading...' })}
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
                          className="touch-target flex-shrink-0 p-1.5 rounded text-slate-400 hover:text-red-500 active:text-red-600 opacity-100 md:opacity-0 md:group-hover/pin:opacity-100 md:group-focus-within/pin:opacity-100 transition-[color,background-color,border-color,box-shadow,opacity] duration-150 motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
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
                  const item = displayItems[virtualRow.index];
                  if (!item) return null;
                  const rowKey = getItemKey(virtualRow.index);
                  if (isTurnPlaceholder(item)) {
                    return (
                      <div
                        key={rowKey}
                        data-index={virtualRow.index}
                        ref={(node) => {
                          measureVirtualRow(rowKey, node);
                        }}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${String(virtualRow.start)}px)`,
                        }}
                      >
                        <TurnPlaceholderRow
                          hiddenCount={item.hiddenCount}
                          onExpand={() => {
                            turnCollapse.toggle(item.turnId);
                          }}
                        />
                      </div>
                    );
                  }
                  if (item.kind === 'timeline') {
                    return (
                      <div
                        key={rowKey}
                        data-index={virtualRow.index}
                        data-msg-index={virtualRow.index}
                        ref={(node) => {
                          measureVirtualRow(rowKey, node);
                        }}
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
                              onAgentSessionSelect={onAgentSessionSelect}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  }
                  if (item.kind === 'subagent') {
                    return (
                      <div
                        key={rowKey}
                        data-index={virtualRow.index}
                        data-msg-index={virtualRow.index}
                        data-timeline-index={item.startIndex}
                        data-subagent-start-index={item.startIndex}
                        data-subagent-id={item.group.subagentId}
                        ref={(node) => {
                          measureVirtualRow(rowKey, node);
                        }}
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
                        key={rowKey}
                        data-index={virtualRow.index}
                        ref={(node) => {
                          measureVirtualRow(rowKey, node);
                        }}
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
                              <JitContextCard event={event} conversationId={conversationId} />
                            ) : (
                              <MemoryCapturedStep event={event} />
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  }

                  const isFocused = focusedMsgIndex === virtualRow.index;
                  const isUserMessage = event.type === 'user_message';
                  const turn =
                    isUserMessage && event.id ? turnByUserMessageId.get(event.id) : undefined;
                  const turnIdForItem = turn?.turnId;
                  const canFoldThisTurn = !!turn && turn.agentIndices.length > 0;
                  const isTurnFolded = !!turnIdForItem && turnCollapse.isCollapsed(turnIdForItem);
                  return (
                    <div
                      key={rowKey}
                      data-index={virtualRow.index}
                      data-msg-index={virtualRow.index}
                      data-msg-id={event.id}
                      ref={(node) => {
                        measureVirtualRow(rowKey, node);
                      }}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${String(virtualRow.start)}px)`,
                      }}
                      className={
                        isFocused
                          ? 'ring-2 ring-blue-400/60 dark:ring-blue-500/50 rounded-lg transition-shadow duration-200'
                          : ''
                      }
                    >
                      <div className="pb-1 group/turn relative">
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
                        {isUserMessage && canFoldThisTurn && turnIdForItem ? (
                          <button
                            type="button"
                            onClick={() => {
                              turnCollapse.toggle(turnIdForItem);
                            }}
                            className={`absolute -bottom-1 right-2 inline-flex items-center gap-1 rounded-md border border-slate-200/70 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 transition-opacity hover:text-slate-800 dark:border-slate-700/60 dark:bg-slate-800 dark:text-slate-400 dark:hover:text-slate-100 ${
                              isTurnFolded
                                ? 'opacity-100'
                                : 'opacity-0 group-hover/turn:opacity-100 focus:opacity-100'
                            }`}
                            aria-label={isTurnFolded ? 'Expand turn' : 'Collapse turn'}
                            data-testid="turn-fold-toggle"
                          >
                            {isTurnFolded
                              ? `Expand (${String(turn.agentIndices.length)})`
                              : 'Collapse'}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>

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
              type="button"
              onClick={contextValue.scroll.scrollToBottom}
              className="touch-target absolute bottom-6 right-6 z-10 flex items-center justify-center w-11 h-11 rounded-full bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 shadow-md border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 hover:shadow-lg transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-150 animate-fade-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
              title={
                scrollButtonChild?.props.title ||
                t('components.messageArea.scrollToBottom', {
                  defaultValue: 'Scroll to bottom',
                })
              }
              aria-label={t('components.messageArea.scrollToBottom', {
                defaultValue: 'Scroll to bottom',
              })}
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
