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
 *   planModeStatus={null}
 *   onViewPlan={handleViewPlan}
 *   onExitPlanMode={handleExitPlanMode}
 * />
 * ```
 *
 * ### Compound Components (Custom rendering)
 * ```tsx
 * <MessageArea timeline={timeline} ...>
 *   <MessageArea.PlanBanner />
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

import { useRef, useEffect, useCallback, useState, memo, Children, createContext } from 'react';

import ReactMarkdown from 'react-markdown';

import { LoadingOutlined } from '@ant-design/icons';
import remarkGfm from 'remark-gfm';

import { MessageBubble } from './MessageBubble';
import { PlanModeBanner } from './PlanModeBanner';
import { StreamingThoughtBubble } from './StreamingThoughtBubble';

import type { TimelineEvent, PlanModeStatus } from '../../types/agent';

// Import and re-export types from separate file
export type {
  MessageAreaRootProps,
  MessageAreaContextValue,
  MessageAreaLoadingProps,
  MessageAreaEmptyProps,
  MessageAreaScrollIndicatorProps,
  MessageAreaScrollButtonProps,
  MessageAreaContentProps,
  MessageAreaPlanBannerProps,
  MessageAreaStreamingContentProps,
  MessageAreaCompound,
} from './message/types';

// Define local type aliases to avoid TS6192 (unused imports)
// These reference the same types as exported above
interface _MessageAreaRootProps {
  timeline: TimelineEvent[];
  streamingContent?: string;
  streamingThought?: string;
  isStreaming: boolean;
  isThinkingStreaming?: boolean;
  isLoading: boolean;
  planModeStatus: PlanModeStatus | null;
  onViewPlan: () => void;
  onExitPlanMode: () => void;
  hasEarlierMessages?: boolean;
  onLoadEarlier?: () => void;
  isLoadingEarlier?: boolean;
  preloadItemCount?: number;
  conversationId?: string | null;
  children?: React.ReactNode;
}

interface _MessageAreaScrollState {
  showScrollButton: boolean;
  showLoadingIndicator: boolean;
  scrollToBottom: () => void;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

interface _MessageAreaContextValue {
  timeline: TimelineEvent[];
  streamingContent?: string;
  streamingThought?: string;
  isStreaming: boolean;
  isThinkingStreaming?: boolean;
  isLoading: boolean;
  planModeStatus: PlanModeStatus | null;
  onViewPlan: () => void;
  onExitPlanMode: () => void;
  hasEarlierMessages: boolean;
  onLoadEarlier?: () => void;
  isLoadingEarlier: boolean;
  preloadItemCount: number;
  conversationId?: string | null;
  scroll: _MessageAreaScrollState;
}

interface _MessageAreaLoadingProps {
  className?: string;
  message?: string;
}

interface _MessageAreaEmptyProps {
  className?: string;
  title?: string;
  subtitle?: string;
}

interface _MessageAreaScrollIndicatorProps {
  className?: string;
  label?: string;
}

interface _MessageAreaScrollButtonProps {
  className?: string;
  title?: string;
}

interface _MessageAreaContentProps {
  className?: string;
}

interface _MessageAreaPlanBannerProps {
  className?: string;
}

interface _MessageAreaStreamingContentProps {
  className?: string;
}

interface _MessageAreaCompound extends React.FC<_MessageAreaRootProps> {
  Provider: React.FC<{ children: React.ReactNode }>;
  Loading: React.FC<_MessageAreaLoadingProps>;
  Empty: React.FC<_MessageAreaEmptyProps>;
  ScrollIndicator: React.FC<_MessageAreaScrollIndicatorProps>;
  ScrollButton: React.FC<_MessageAreaScrollButtonProps>;
  Content: React.FC<_MessageAreaContentProps>;
  PlanBanner: React.FC<_MessageAreaPlanBannerProps>;
  StreamingContent: React.FC<_MessageAreaStreamingContentProps>;
  Root: React.FC<_MessageAreaRootProps>;
}

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const LOADING_SYMBOL = Symbol('MessageAreaLoading');
const EMPTY_SYMBOL = Symbol('MessageAreaEmpty');
const SCROLL_INDICATOR_SYMBOL = Symbol('MessageAreaScrollIndicator');
const SCROLL_BUTTON_SYMBOL = Symbol('MessageAreaScrollButton');
const CONTENT_SYMBOL = Symbol('MessageAreaContent');
const PLAN_BANNER_SYMBOL = Symbol('MessageAreaPlanBanner');
const STREAMING_CONTENT_SYMBOL = Symbol('MessageAreaStreamingContent');

// ========================================
// Context
// ========================================

const MessageAreaContext = createContext<_MessageAreaContextValue | null>(null);

export const useMessageArea = () => {
  const context = MessageAreaContext;
  if (!context) {
    throw new Error('useMessageArea must be used within MessageArea');
  }
  return context;
};

// ========================================
// Utility Functions
// ========================================

// Check if scroll is near bottom
const isNearBottom = (element: HTMLElement, threshold = 100): boolean => {
  const { scrollHeight, scrollTop, clientHeight } = element;
  return scrollHeight - scrollTop - clientHeight < threshold;
};

// ========================================
// Sub-Components (Marker Components)
// ========================================

function LoadingMarker(_props: _MessageAreaLoadingProps) {
  return null;
}
function EmptyMarker(_props: _MessageAreaEmptyProps) {
  return null;
}
function ScrollIndicatorMarker(_props: _MessageAreaScrollIndicatorProps) {
  return null;
}
function ScrollButtonMarker(_props: _MessageAreaScrollButtonProps) {
  return null;
}
function ContentMarker(_props: _MessageAreaContentProps) {
  return null;
}
function PlanBannerMarker(_props: _MessageAreaPlanBannerProps) {
  return null;
}
function StreamingContentMarker(_props: _MessageAreaStreamingContentProps) {
  return null;
}

// Attach symbols
;(LoadingMarker as any)[LOADING_SYMBOL] = true;
;(EmptyMarker as any)[EMPTY_SYMBOL] = true;
;(ScrollIndicatorMarker as any)[SCROLL_INDICATOR_SYMBOL] = true;
;(ScrollButtonMarker as any)[SCROLL_BUTTON_SYMBOL] = true;
;(ContentMarker as any)[CONTENT_SYMBOL] = true;
;(PlanBannerMarker as any)[PLAN_BANNER_SYMBOL] = true;
;(StreamingContentMarker as any)[STREAMING_CONTENT_SYMBOL] = true;

// Set display names for testing
;(LoadingMarker as any).displayName = 'MessageAreaLoading';
;(EmptyMarker as any).displayName = 'MessageAreaEmpty';
;(ScrollIndicatorMarker as any).displayName = 'MessageAreaScrollIndicator';
;(ScrollButtonMarker as any).displayName = 'MessageAreaScrollButton';
;(ContentMarker as any).displayName = 'MessageAreaContent';
;(PlanBannerMarker as any).displayName = 'MessageAreaPlanBanner';
;(StreamingContentMarker as any).displayName = 'MessageAreaStreamingContent';

// ========================================
// Actual Sub-Component Implementations
// ========================================

// Internal Loading component
const InternalLoading: React.FC<_MessageAreaLoadingProps & { context: _MessageAreaContextValue }> = ({ message, context }) => {
  if (!context.isLoading) return null;
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <LoadingOutlined className="text-4xl text-primary mb-4" spin />
        <p className="text-slate-500">{message || 'Loading conversation...'}</p>
      </div>
    </div>
  );
};

// Internal Empty component
const InternalEmpty: React.FC<_MessageAreaEmptyProps & { context: _MessageAreaContextValue }> = ({ title, subtitle, context }) => {
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

const MessageAreaInner: React.FC<_MessageAreaRootProps> = memo(({
  timeline,
  streamingContent,
  streamingThought,
  isStreaming,
  isThinkingStreaming,
  isLoading,
  planModeStatus,
  onViewPlan,
  onExitPlanMode,
  hasEarlierMessages = false,
  onLoadEarlier,
  isLoadingEarlier: propIsLoadingEarlier = false,
  preloadItemCount = 10,
  conversationId,
  children,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [showLoadingIndicator, setShowLoadingIndicator] = useState(false);

  // Parse children to detect sub-components
  const childrenArray = Children.toArray(children);
  const loadingChild = childrenArray.find((child: any) => child?.type?.[LOADING_SYMBOL]) as any;
  const emptyChild = childrenArray.find((child: any) => child?.type?.[EMPTY_SYMBOL]) as any;
  const scrollIndicatorChild = childrenArray.find((child: any) => child?.type?.[SCROLL_INDICATOR_SYMBOL]) as any;
  const scrollButtonChild = childrenArray.find((child: any) => child?.type?.[SCROLL_BUTTON_SYMBOL]) as any;
  const contentChild = childrenArray.find((child: any) => child?.type?.[CONTENT_SYMBOL]) as any;
  const planBannerChild = childrenArray.find((child: any) => child?.type?.[PLAN_BANNER_SYMBOL]) as any;
  const streamingContentChild = childrenArray.find((child: any) => child?.type?.[STREAMING_CONTENT_SYMBOL]) as any;

  // Determine if using compound mode
  const hasSubComponents = loadingChild || emptyChild || scrollIndicatorChild ||
    scrollButtonChild || contentChild || planBannerChild || streamingContentChild;

  // In legacy mode, include all sections by default
  // In compound mode, only include explicitly specified sections
  const includeLoading = hasSubComponents ? !!loadingChild : true;
  const includeEmpty = hasSubComponents ? !!emptyChild : true;
  const includeScrollIndicator = hasSubComponents ? !!scrollIndicatorChild : true;
  const includeScrollButton = hasSubComponents ? !!scrollButtonChild : true;
  const includeContent = hasSubComponents ? !!contentChild : true;
  const includePlanBanner = hasSubComponents ? !!planBannerChild : true;
  const includeStreamingContent = hasSubComponents ? !!streamingContentChild : true;

  // Pagination state refs
  const prevTimelineLengthRef = useRef(timeline.length);
  const previousScrollHeightRef = useRef(0);
  const previousScrollTopRef = useRef(0);
  const isLoadingEarlierRef = useRef(false);
  const isInitialLoadRef = useRef(true);
  const hasScrolledInitiallyRef = useRef(false);
  const loadingIndicatorTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const lastLoadTimeRef = useRef(0);

  // Track if user has manually scrolled up during streaming
  const userScrolledUpRef = useRef(false);

  // Context value
  const contextValue: _MessageAreaContextValue = {
    timeline,
    streamingContent,
    streamingThought,
    isStreaming,
    isThinkingStreaming,
    isLoading,
    planModeStatus,
    onViewPlan,
    onExitPlanMode,
    hasEarlierMessages,
    onLoadEarlier,
    isLoadingEarlier: propIsLoadingEarlier,
    preloadItemCount,
    conversationId,
    scroll: {
      showScrollButton,
      showLoadingIndicator,
      scrollToBottom: useCallback(() => {
        const container = containerRef.current;
        if (!container) return;
        container.scrollTo({
          top: container.scrollHeight,
          behavior: 'smooth',
        });
        setShowScrollButton(false);
      }, []),
      containerRef,
    },
  };

  // Save scroll position before loading earlier messages
  const saveScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    previousScrollHeightRef.current = container.scrollHeight;
    previousScrollTopRef.current = container.scrollTop;
  }, []);

  // Restore scroll position after loading earlier messages
  const restoreScrollPosition = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const newScrollHeight = container.scrollHeight;
    const heightDifference = newScrollHeight - previousScrollHeightRef.current;

    const targetScrollTop = previousScrollTopRef.current + heightDifference;

    container.scrollTop = targetScrollTop;

    previousScrollHeightRef.current = 0;
    previousScrollTopRef.current = 0;
  }, []);

  // Aggressive preload logic
  const checkAndPreload = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    if (
      !isLoadingEarlierRef.current &&
      !propIsLoadingEarlier &&
      hasEarlierMessages &&
      onLoadEarlier
    ) {
      const { scrollTop } = container;

      const avgMessageHeight = 100;
      const visibleItemsFromTop = Math.ceil(scrollTop / avgMessageHeight);

      if (visibleItemsFromTop < preloadItemCount) {
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
  }, [hasEarlierMessages, onLoadEarlier, preloadItemCount, saveScrollPosition, propIsLoadingEarlier]);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const container = containerRef.current;
    if (!container || isLoading) return;

    checkAndPreload();

    const atBottom = isNearBottom(container, 100);
    setShowScrollButton(!atBottom && timeline.length > 0);

    if (isStreaming && !atBottom) {
      userScrolledUpRef.current = true;
    } else if (isStreaming && atBottom) {
      userScrolledUpRef.current = false;
    }
  }, [isLoading, timeline.length, checkAndPreload, isStreaming]);

  // Handle timeline changes
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const currentTimelineLength = timeline.length;
    const previousTimelineLength = prevTimelineLengthRef.current;
    const hasNewMessages = currentTimelineLength > previousTimelineLength;
    const isInitialLoad = isInitialLoadRef.current && currentTimelineLength > 0;

    if (isInitialLoad && !hasScrolledInitiallyRef.current) {
      hasScrolledInitiallyRef.current = true;
      isInitialLoadRef.current = false;

      requestAnimationFrame(() => {
        if (containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      });
      prevTimelineLengthRef.current = currentTimelineLength;
      return;
    }

    if (hasNewMessages && !isLoading && previousScrollHeightRef.current > 0) {
      restoreScrollPosition();
      prevTimelineLengthRef.current = currentTimelineLength;

      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
        loadingIndicatorTimeoutRef.current = null;
      }
      setTimeout(() => setShowLoadingIndicator(false), 0);
      return;
    }

    if (hasNewMessages) {
      if (isStreaming || isNearBottom(container, 200)) {
        requestAnimationFrame(() => {
          if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
          }
        });
        setTimeout(() => setShowScrollButton(false), 0);
      } else {
        setTimeout(() => setShowScrollButton(true), 0);
      }
    }

    prevTimelineLengthRef.current = currentTimelineLength;
  }, [timeline.length, isStreaming, isLoading, restoreScrollPosition]);

  // Auto-scroll when streaming content updates
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    if (isStreaming && !userScrolledUpRef.current) {
      requestAnimationFrame(() => {
        if (containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      });
    }
  }, [streamingContent, streamingThought, isStreaming]);

  // Reset scroll state when conversation changes
  useEffect(() => {
    isInitialLoadRef.current = true;
    hasScrolledInitiallyRef.current = false;
    prevTimelineLengthRef.current = 0;
    previousScrollHeightRef.current = 0;
    previousScrollTopRef.current = 0;
    isLoadingEarlierRef.current = false;
    userScrolledUpRef.current = false;

    const timeoutId = setTimeout(() => {
      const container = containerRef.current;
      if (container && timeline.length > 0) {
        container.scrollTop = container.scrollHeight;
        isInitialLoadRef.current = false;
        hasScrolledInitiallyRef.current = true;
        prevTimelineLengthRef.current = timeline.length;
      }
    }, 100);

    return () => clearTimeout(timeoutId);
  }, [conversationId]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (loadingIndicatorTimeoutRef.current) {
        clearTimeout(loadingIndicatorTimeoutRef.current);
      }
    };
  }, []);

  // Reset userScrolledUpRef when streaming ends
  useEffect(() => {
    if (!isStreaming) {
      userScrolledUpRef.current = false;
    }
  }, [isStreaming]);

  // Determine states
  const shouldShowLoading = (propIsLoadingEarlier && hasEarlierMessages) || (showLoadingIndicator && hasEarlierMessages);
  const showLoadingState = isLoading && timeline.length === 0;
  const showEmptyState = !isLoading && timeline.length === 0;

  return (
    <MessageAreaContext.Provider value={contextValue}>
      <div className="h-full w-full relative flex flex-col overflow-hidden">

        {/* Plan Mode Banner */}
        {includePlanBanner && planModeStatus?.is_in_plan_mode && (
          <div className="flex-shrink-0">
            <PlanModeBanner
              status={planModeStatus}
              onViewPlan={onViewPlan}
              onExit={onExitPlanMode}
            />
          </div>
        )}

        {/* Loading state */}
        {includeLoading && showLoadingState && <InternalLoading context={contextValue} {...loadingChild?.props} />}

        {/* Empty state */}
        {includeEmpty && showEmptyState && <InternalEmpty context={contextValue} {...emptyChild?.props} />}

        {/* Scroll indicator for earlier messages */}
        {includeScrollIndicator && shouldShowLoading && (
          <div className="absolute top-2 left-0 right-0 z-10 flex justify-center pointer-events-none" data-testid="scroll-indicator">
            <div className="flex items-center px-3 py-1.5 bg-slate-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-full shadow-sm border border-slate-200/50 dark:border-slate-700/50 opacity-70">
              <LoadingOutlined className="text-primary mr-2" spin />
              <span className="text-xs text-slate-500">{scrollIndicatorChild?.props?.label || '加载中...'}</span>
            </div>
          </div>
        )}

        {/* Message Container with Content */}
        {includeContent && !showLoadingState && !showEmptyState && (
          <div
            ref={containerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto chat-scrollbar p-4 md:p-6 pb-24 min-h-0"
            data-testid="message-container"
          >
            <div className="w-full space-y-3">
              {timeline.map((event, index) => (
                <MessageBubble
                  key={event.id || `event-${index}`}
                  event={event}
                  isStreaming={isStreaming && index === timeline.length - 1}
                  allEvents={timeline}
                />
              ))}

              {/* Streaming thought indicator */}
              {includeStreamingContent && (isThinkingStreaming || streamingThought) && (
                <StreamingThoughtBubble
                  content={streamingThought || ''}
                  isStreaming={!!isThinkingStreaming}
                />
              )}

              {/* Streaming content indicator */}
              {includeStreamingContent && isStreaming && streamingContent && !isThinkingStreaming && (
                <div className="flex items-start gap-3 animate-slide-up">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0">
                    <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </div>
                  <div className="flex-1 max-w-[85%] md:max-w-[75%]">
                    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
                      <div className="prose prose-sm dark:prose-invert max-w-none font-sans">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
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
            className="absolute bottom-6 right-6 z-10 flex items-center justify-center w-10 h-10 rounded-full bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 shadow-md border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 hover:shadow-lg transition-all animate-fade-in"
            title={scrollButtonChild?.props?.title || 'Scroll to bottom'}
            data-testid="scroll-button"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
            </svg>
          </button>
        )}
      </div>
    </MessageAreaContext.Provider>
  );
});

MessageAreaInner.displayName = 'MessageAreaInner';

// Create compound component with sub-components
const MessageAreaMemo = memo(MessageAreaInner);
MessageAreaMemo.displayName = 'MessageArea';

// Create compound component object
const MessageAreaCompound = MessageAreaMemo as unknown as _MessageAreaCompound;
MessageAreaCompound.Provider = ({ children }: { children: React.ReactNode }) => (
  <MessageAreaContext.Provider value={null as any}>{children}</MessageAreaContext.Provider>
);
MessageAreaCompound.Loading = LoadingMarker;
MessageAreaCompound.Empty = EmptyMarker;
MessageAreaCompound.ScrollIndicator = ScrollIndicatorMarker;
MessageAreaCompound.ScrollButton = ScrollButtonMarker;
MessageAreaCompound.Content = ContentMarker;
MessageAreaCompound.PlanBanner = PlanBannerMarker;
MessageAreaCompound.StreamingContent = StreamingContentMarker;
MessageAreaCompound.Root = MessageAreaMemo;

// Export compound component
export const MessageArea = MessageAreaCompound;

export default MessageArea;
