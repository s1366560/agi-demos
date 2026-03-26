/**
 * useMessageAreaScroll - Scroll management and pagination for MessageArea.
 *
 * Extracts scroll refs, scroll-to-bottom, save/restore scroll position,
 * handleScroll, checkAndPreload (pagination), and related effects from
 * MessageAreaInner to reduce the component size and improve separation
 * of concerns.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { isNearBottom } from './markers';

import type { TimelineEvent } from '../../../types/agent';

// ========================================
// Types
// ========================================

export interface UseMessageAreaScrollParams {
  containerRef: React.RefObject<HTMLDivElement | null>;
  timeline: TimelineEvent[];
  isStreaming: boolean;
  isThinkingStreaming: boolean;
  isLoading: boolean;
  streamingContent: string | undefined;
  streamingThought: string | undefined;
  hasEarlierMessages: boolean;
  onLoadEarlier?: (() => void) | undefined;
  propIsLoadingEarlier: boolean;
  preloadItemCount: number;
}

export interface UseMessageAreaScrollReturn {
  showScrollButton: boolean;
  showLoadingIndicator: boolean;
  scrollToBottom: () => void;
  handleScroll: () => void;
  // Refs exposed for the conversation-switch effect in MessageArea
  isInitialLoadRef: React.MutableRefObject<boolean>;
  hasScrolledInitiallyRef: React.MutableRefObject<boolean>;
  prevTimelineLengthRef: React.MutableRefObject<number>;
  previousScrollHeightRef: React.MutableRefObject<number>;
  previousScrollTopRef: React.MutableRefObject<number>;
  isLoadingEarlierRef: React.MutableRefObject<boolean>;
  userScrolledUpRef: React.MutableRefObject<boolean>;
  isSwitchingConversationRef: React.MutableRefObject<boolean>;
  isPositioningRef: React.MutableRefObject<boolean>;
  lastConversationIdRef: React.MutableRefObject<string | null | undefined>;
}

// ========================================
// Hook
// ========================================

export function useMessageAreaScroll(
  params: UseMessageAreaScrollParams
): UseMessageAreaScrollReturn {
  const {
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
  } = params;

  const [showScrollButton, setShowScrollButton] = useState(false);
  const [showLoadingIndicator, setShowLoadingIndicator] = useState(false);

  // Pagination state refs
  const prevTimelineLengthRef = useRef(timeline.length);
  const previousScrollHeightRef = useRef(0);
  const previousScrollTopRef = useRef(0);
  const isLoadingEarlierRef = useRef(false);
  const isInitialLoadRef = useRef(true);
  const hasScrolledInitiallyRef = useRef(false);
  const loadingIndicatorTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastLoadTimeRef = useRef(0);
  // Suppress scroll events during initial positioning to prevent scrollbar jitter
  const isPositioningRef = useRef(false);

  // Track if user has manually scrolled up during streaming
  const userScrolledUpRef = useRef(false);

  // Track conversation switch to prevent scroll jitter
  const isSwitchingConversationRef = useRef(false);
  const lastConversationIdRef = useRef<string | null | undefined>(undefined);

  const scrollToBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    container.scrollTo({
      top: container.scrollHeight,
      behavior: 'smooth',
    });
    setShowScrollButton(false);
    userScrolledUpRef.current = false;
  }, [containerRef]);

  // Save scroll position before loading earlier messages
  const saveScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    previousScrollHeightRef.current = container.scrollHeight;
    previousScrollTopRef.current = container.scrollTop;
  }, [containerRef]);

  // Restore scroll position after loading earlier messages
  const restoreScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    isPositioningRef.current = true;
    const newScrollHeight = container.scrollHeight;
    const heightDifference = newScrollHeight - previousScrollHeightRef.current;

    const targetScrollTop = previousScrollTopRef.current + heightDifference;

    container.scrollTop = targetScrollTop;

    previousScrollHeightRef.current = 0;
    previousScrollTopRef.current = 0;
    // Release guard after layout settles
    requestAnimationFrame(() => {
      isPositioningRef.current = false;
    });
  }, [containerRef]);

  // Aggressive preload logic with screen height adaptation
  const checkAndPreload = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    if (
      !isLoadingEarlierRef.current &&
      !propIsLoadingEarlier &&
      hasEarlierMessages &&
      onLoadEarlier
    ) {
      const { scrollTop, scrollHeight, clientHeight } = container;

      // If content doesn't fill the container (no scrollbar needed),
      // trigger loading immediately to fill the screen
      const contentFillsContainer = scrollHeight > clientHeight + 10; // 10px tolerance

      const avgMessageHeight = 100;
      const visibleItemsFromTop = Math.ceil(scrollTop / avgMessageHeight);

      // Trigger load when:
      // 1. Content doesn't fill container (need more messages to fill screen), OR
      // 2. User has scrolled near the top (visibleItemsFromTop < threshold)
      const shouldTriggerLoad = !contentFillsContainer || visibleItemsFromTop < preloadItemCount;

      if (shouldTriggerLoad) {
        const now = Date.now();
        if (now - lastLoadTimeRef.current < 300) return;

        saveScrollPosition();

        isLoadingEarlierRef.current = true;
        lastLoadTimeRef.current = now;

        loadingIndicatorTimeoutRef.current = setTimeout(() => {
          setShowLoadingIndicator(true);
        }, 300);

        onLoadEarlier();

        setTimeout(() => {
          isLoadingEarlierRef.current = false;
        }, 500);
      }
    }
  }, [
    containerRef,
    hasEarlierMessages,
    onLoadEarlier,
    preloadItemCount,
    saveScrollPosition,
    propIsLoadingEarlier,
  ]);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container || isLoading || isSwitchingConversationRef.current || isPositioningRef.current)
      return;

    checkAndPreload();

    const atBottom = isNearBottom(container, 100);
    setShowScrollButton(!atBottom && timeline.length > 0);

    if (isStreaming && !atBottom) {
      userScrolledUpRef.current = true;
    } else if (isStreaming && atBottom) {
      userScrolledUpRef.current = false;
    }
  }, [containerRef, isLoading, timeline.length, checkAndPreload, isStreaming]);

  // Handle timeline changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const currentTimelineLength = timeline.length;
    const previousTimelineLength = prevTimelineLengthRef.current;
    const hasNewMessages = currentTimelineLength > previousTimelineLength;
    const isInitialLoad = isInitialLoadRef.current && currentTimelineLength > 0;

    // Handle initial load -- also covers data arriving after conversation switch
    if (isInitialLoad && !hasScrolledInitiallyRef.current) {
      hasScrolledInitiallyRef.current = true;
      isInitialLoadRef.current = false;
      prevTimelineLengthRef.current = currentTimelineLength;
      isPositioningRef.current = true;

      // Double-rAF: first frame for virtualizer layout, second for scroll
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
          }
          // Allow scroll events after positioning settles
          requestAnimationFrame(() => {
            isPositioningRef.current = false;
          });
        });
      });
      return;
    }

    // Handle pagination scroll restoration (skip if switching conversation)
    if (hasNewMessages && !isLoading && previousScrollHeightRef.current > 0) {
      if (!isSwitchingConversationRef.current) {
        restoreScrollPosition();
      }
      prevTimelineLengthRef.current = currentTimelineLength;

      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
        loadingIndicatorTimeoutRef.current = null;
      }
      setTimeout(() => {
        setShowLoadingIndicator(false);
      }, 0);
      return;
    }

    // Handle new messages - clear switching flag and auto-scroll
    if (hasNewMessages) {
      // Clear switching flag when new messages arrive
      isSwitchingConversationRef.current = false;

      if (isStreaming || isNearBottom(container, 200)) {
        requestAnimationFrame(() => {
          if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
          }
        });
        setTimeout(() => {
          setShowScrollButton(false);
        }, 0);
      } else {
        setTimeout(() => {
          setShowScrollButton(true);
        }, 0);
      }
    }

    prevTimelineLengthRef.current = currentTimelineLength;
    // groupedItems.length is intentionally excluded from deps when virtualizer
    // is not available inside this hook -- the component passes it in
  }, [timeline.length, isStreaming, isLoading, restoreScrollPosition, containerRef]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: streamingContent and streamingThought are intentional trigger deps
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const hasStreamingContent = (streamingContent ?? '').trim().length > 0;
    const hasStreamingThought = (streamingThought ?? '').trim().length > 0;
    const thoughtOnlyStreaming = isThinkingStreaming && hasStreamingThought && !hasStreamingContent;

    if (isStreaming && !userScrolledUpRef.current && !thoughtOnlyStreaming) {
      isSwitchingConversationRef.current = false;

      requestAnimationFrame(() => {
        if (containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      });
    }
  }, [streamingContent, streamingThought, isStreaming, isThinkingStreaming, containerRef]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
      }
    };
  }, []);

  // Clear loading indicator when hasEarlierMessages becomes false
  useEffect(() => {
    if (!hasEarlierMessages) {
      queueMicrotask(() => {
        setShowLoadingIndicator(false);
      });
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
        loadingIndicatorTimeoutRef.current = null;
      }
    }
  }, [hasEarlierMessages]);

  // Reset userScrolledUpRef when streaming ends
  useEffect(() => {
    if (!isStreaming) {
      userScrolledUpRef.current = false;
    }
  }, [isStreaming]);

  return {
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
  };
}
