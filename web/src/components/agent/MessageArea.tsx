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

import { useRef, useEffect, useCallback, useState, memo, Children, createContext, useMemo } from 'react';

import ReactMarkdown from 'react-markdown';

import { LoadingOutlined } from '@ant-design/icons';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Pin, PinOff, ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { useAgentV3Store } from '../../stores/agentV3';
import { useConversationsStore } from '../../stores/agent/conversationsStore';

import { AgentStatePill } from './chat/AgentStatePill';
import { ConversationSummaryCard } from './chat/ConversationSummaryCard';
import { useMarkdownPlugins } from './chat/markdownPlugins';
import { PlanProgressBar } from './chat/PlanProgressBar';
import { SuggestionChips } from './chat/SuggestionChips';
import { ThinkingBlock } from './chat/ThinkingBlock';
import { MessageBubble } from './MessageBubble';
import { PlanModeBanner } from './PlanModeBanner';
import { MARKDOWN_PROSE_CLASSES } from './styles';
import { ExecutionTimeline } from './timeline/ExecutionTimeline';

import type { TimelineStep } from './timeline/ExecutionTimeline';
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

/**
 * Groups consecutive act/observe timeline events into ExecutionTimeline groups.
 * Non-tool events pass through as individual items.
 */
type GroupedItem =
  | { kind: 'event'; event: TimelineEvent; index: number }
  | { kind: 'timeline'; steps: TimelineStep[]; startIndex: number };

function groupTimelineEvents(timeline: TimelineEvent[]): GroupedItem[] {
  const result: GroupedItem[] = [];
  let currentSteps: TimelineStep[] = [];
  let groupStartIndex = 0;

  // Build observe lookup by execution_id
  const observeByExecId = new Map<string, TimelineEvent>();
  // Fallback: build observe lookup by toolName for events without execution_id
  const observeByToolName = new Map<string, TimelineEvent[]>();
  for (const ev of timeline) {
    if (ev.type === 'observe') {
      if ((ev as any).execution_id) {
        observeByExecId.set((ev as any).execution_id, ev);
      }
      const name = (ev as any).toolName || 'unknown';
      const list = observeByToolName.get(name) || [];
      list.push(ev);
      observeByToolName.set(name, list);
    }
  }

  // Track which observe events have been consumed by fallback matching
  const consumedObserves = new Set<string>();

  const flushGroup = () => {
    if (currentSteps.length >= 1) {
      result.push({ kind: 'timeline', steps: currentSteps, startIndex: groupStartIndex });
    }
    currentSteps = [];
  };

  for (let i = 0; i < timeline.length; i++) {
    const event = timeline[i];

    if (event.type === 'act') {
      if (currentSteps.length === 0) groupStartIndex = i;

      const act = event as any;
      // Priority 1: match by execution_id
      let obs = act.execution_id ? observeByExecId.get(act.execution_id) : undefined;
      // Priority 2: fallback to toolName matching
      if (!obs) {
        const candidates = observeByToolName.get(act.toolName) || [];
        for (const cand of candidates) {
          if (!consumedObserves.has(cand.id) && (cand as any).timestamp >= act.timestamp) {
            obs = cand;
            consumedObserves.add(cand.id);
            break;
          }
        }
      }
      const o = obs as any;

      const step: TimelineStep = {
        id: act.execution_id || act.id || `step-${i}`,
        toolName: act.toolName || 'unknown',
        status: o ? (o.isError ? 'error' : 'success') : 'running',
        input: act.toolInput,
        output: o?.toolOutput,
        isError: o?.isError,
        duration:
          o && act.timestamp && o.timestamp
            ? (o.timestamp - act.timestamp)
            : undefined,
      };
      currentSteps.push(step);
    } else if (event.type === 'observe') {
      // Skip - handled as part of act
      continue;
    } else {
      flushGroup();
      result.push({ kind: 'event', event, index: i });
    }
  }
  flushGroup();

  return result;
}

/**
 * Estimate item height for the virtualizer based on item type.
 * Better estimates reduce scroll jumping when items are measured for real.
 */
function estimateGroupedItemHeight(item: GroupedItem): number {
  if (item.kind === 'timeline') {
    return 80 + item.steps.length * 40;
  }
  const { event } = item;
  switch (event.type) {
    case 'user_message':
      return 100;
    case 'assistant_message': {
      const content = ('content' in event ? (event as any).content : '') || '';
      return estimateMarkdownHeight(content);
    }
    default:
      return 80;
  }
}

/**
 * Estimate rendered height of markdown content by analyzing structure.
 * Counts code blocks, line breaks, and text density for better accuracy.
 */
function estimateMarkdownHeight(content: string): number {
  if (!content) return 80;

  const LINE_HEIGHT = 24;
  const CODE_LINE_HEIGHT = 20;
  const BASE_PADDING = 60; // bubble chrome (avatar, margins, padding)
  let height = BASE_PADDING;

  // Count fenced code blocks and estimate their height
  const codeBlockRegex = /```[\s\S]*?```/g;
  let remaining = content;
  let match: RegExpExecArray | null;
  while ((match = codeBlockRegex.exec(content)) !== null) {
    const block = match[0];
    const lines = block.split('\n').length;
    // Code block: header(32) + lines + padding(24)
    height += 32 + lines * CODE_LINE_HEIGHT + 24;
    remaining = remaining.replace(block, '');
  }

  // Count lines in remaining non-code text
  const textLines = remaining.split('\n');
  for (const line of textLines) {
    const trimmed = line.trim();
    if (!trimmed) {
      height += 8; // empty line spacing
    } else if (trimmed.startsWith('#')) {
      height += 36; // heading
    } else if (trimmed.startsWith('|')) {
      height += 32; // table row
    } else if (trimmed.startsWith('- ') || trimmed.startsWith('* ') || /^\d+\./.test(trimmed)) {
      height += LINE_HEIGHT; // list item
    } else {
      // Regular text: wrap estimate (~80 chars per visual line)
      height += Math.max(1, Math.ceil(trimmed.length / 80)) * LINE_HEIGHT;
    }
  }

  return Math.max(80, height);
}

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
  suggestions?: string[];
  onSuggestionSelect?: (suggestion: string) => void;
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
(LoadingMarker as any)[LOADING_SYMBOL] = true;
(EmptyMarker as any)[EMPTY_SYMBOL] = true;
(ScrollIndicatorMarker as any)[SCROLL_INDICATOR_SYMBOL] = true;
(ScrollButtonMarker as any)[SCROLL_BUTTON_SYMBOL] = true;
(ContentMarker as any)[CONTENT_SYMBOL] = true;
(PlanBannerMarker as any)[PLAN_BANNER_SYMBOL] = true;
(StreamingContentMarker as any)[STREAMING_CONTENT_SYMBOL] = true;

// Set display names for testing
(LoadingMarker as any).displayName = 'MessageAreaLoading';
(EmptyMarker as any).displayName = 'MessageAreaEmpty';
(ScrollIndicatorMarker as any).displayName = 'MessageAreaScrollIndicator';
(ScrollButtonMarker as any).displayName = 'MessageAreaScrollButton';
(ContentMarker as any).displayName = 'MessageAreaContent';
(PlanBannerMarker as any).displayName = 'MessageAreaPlanBanner';
(StreamingContentMarker as any).displayName = 'MessageAreaStreamingContent';

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
        <LoadingOutlined className="text-4xl text-primary mb-4" spin />
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
// Streaming Tool Preparation Indicator
// ========================================

const StreamingToolPreparation: React.FC = memo(() => {
  const agentState = useAgentV3Store((s) => s.agentState);
  const activeToolCalls = useAgentV3Store((s) => s.activeToolCalls);

  if (agentState !== 'preparing') return null;

  const preparingTools = Array.from(activeToolCalls.entries()).filter(
    ([, call]) => call.status === 'preparing'
  );
  if (preparingTools.length === 0) return null;

  return (
    <>
      {preparingTools.map(([toolName, call]) => (
        <StreamingToolCard
          key={toolName}
          toolName={toolName}
          partialArguments={call.partialArguments}
        />
      ))}
    </>
  );
});
StreamingToolPreparation.displayName = 'StreamingToolPreparation';

const StreamingToolCard: React.FC<{ toolName: string; partialArguments?: string }> = memo(
  ({ toolName, partialArguments }) => {
    const argsRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
      if (argsRef.current) {
        argsRef.current.scrollTop = argsRef.current.scrollHeight;
      }
    }, [partialArguments]);

    return (
      <div className="flex items-start gap-3 mb-4 animate-fade-in-up">
        <div className="w-8 h-8 rounded-xl bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-[18px]">
            construction
          </span>
        </div>
        <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
          <div className="bg-white dark:bg-slate-800/90 border border-blue-200/80 dark:border-blue-700/50 rounded-2xl rounded-tl-sm overflow-hidden shadow-sm">
            <div className="px-4 py-3 bg-blue-50/50 dark:bg-blue-900/10 border-b border-blue-200/50 dark:border-blue-700/30 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                  {toolName}
                </span>
              </div>
              <div className="flex items-center gap-2 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-500/10 text-blue-600 text-[10px] font-bold uppercase tracking-wider">
                <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                Preparing
              </div>
            </div>
            {partialArguments && (
              <div className="p-3">
                <div
                  ref={argsRef}
                  className="px-3 py-2 bg-blue-50 dark:bg-blue-500/5 border border-blue-200/50 dark:border-blue-500/20 rounded-lg text-xs font-mono text-slate-600 dark:text-slate-400 overflow-x-auto max-h-24 overflow-y-auto"
                >
                  <pre className="whitespace-pre-wrap break-words">
                    {partialArguments}
                    <span className="inline-block w-1.5 h-3.5 bg-blue-500 animate-pulse ml-0.5 align-middle" />
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }
);
StreamingToolCard.displayName = 'StreamingToolCard';

// ========================================
// Conversation Summary Wrapper
// ========================================

const ConversationSummaryCardWrapper: React.FC<{
  conversationId?: string | null;
}> = memo(({ conversationId }) => {
  const currentConversation = useConversationsStore((s) => s.currentConversation);
  const generateConversationSummary = useConversationsStore(
    (s) => s.generateConversationSummary
  );

  if (!conversationId || !currentConversation || currentConversation.id !== conversationId) {
    return null;
  }

  return (
    <ConversationSummaryCard
      summary={currentConversation.summary ?? null}
      conversationId={conversationId}
      onRegenerate={generateConversationSummary}
    />
  );
});
ConversationSummaryCardWrapper.displayName = 'ConversationSummaryCardWrapper';

// ========================================
// Main Component
// ========================================

const MessageAreaInner: React.FC<_MessageAreaRootProps> = memo(
  ({
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
    suggestions,
    onSuggestionSelect,
    children,
  }) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const [showScrollButton, setShowScrollButton] = useState(false);
    const [showLoadingIndicator, setShowLoadingIndicator] = useState(false);
    const [pinnedCollapsed, setPinnedCollapsed] = useState(false);
    const { t } = useTranslation();
    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(streamingContent);

    // Memoize grouped timeline items to avoid re-grouping on every render
    const groupedItems = useMemo(() => groupTimelineEvents(timeline), [timeline]);

    const pinnedEventIds = useAgentV3Store((s) => s.pinnedEventIds);
    const togglePinEvent = useAgentV3Store((s) => s.togglePinEvent);

    const pinnedEvents = useMemo(
      () => timeline.filter((e) => e.id && pinnedEventIds.has(e.id)),
      [timeline, pinnedEventIds]
    );

    // Parse children to detect sub-components
    const childrenArray = Children.toArray(children);
    const loadingChild = childrenArray.find((child: any) => child?.type?.[LOADING_SYMBOL]) as any;
    const emptyChild = childrenArray.find((child: any) => child?.type?.[EMPTY_SYMBOL]) as any;
    const scrollIndicatorChild = childrenArray.find(
      (child: any) => child?.type?.[SCROLL_INDICATOR_SYMBOL]
    ) as any;
    const scrollButtonChild = childrenArray.find(
      (child: any) => child?.type?.[SCROLL_BUTTON_SYMBOL]
    ) as any;
    const contentChild = childrenArray.find((child: any) => child?.type?.[CONTENT_SYMBOL]) as any;
    const planBannerChild = childrenArray.find(
      (child: any) => child?.type?.[PLAN_BANNER_SYMBOL]
    ) as any;
    const streamingContentChild = childrenArray.find(
      (child: any) => child?.type?.[STREAMING_CONTENT_SYMBOL]
    ) as any;

    // Determine if using compound mode
    const hasSubComponents =
      loadingChild ||
      emptyChild ||
      scrollIndicatorChild ||
      scrollButtonChild ||
      contentChild ||
      planBannerChild ||
      streamingContentChild;

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
    
    // Track conversation switch to prevent scroll jitter
    const isSwitchingConversationRef = useRef(false);
    const lastConversationIdRef = useRef(conversationId);

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
          userScrolledUpRef.current = false;
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
      hasEarlierMessages,
      onLoadEarlier,
      preloadItemCount,
      saveScrollPosition,
      propIsLoadingEarlier,
    ]);

    // Handle scroll events
    const handleScroll = useCallback(() => {
      const container = containerRef.current;
      if (!container || isLoading || isSwitchingConversationRef.current) return;

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

      // Handle initial load (skip if conversation switch is in progress — handled separately)
      if (isInitialLoad && !hasScrolledInitiallyRef.current && !isSwitchingConversationRef.current) {
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
        setTimeout(() => setShowLoadingIndicator(false), 0);
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
        // Clear switching flag during streaming (user is actively viewing this conversation)
        isSwitchingConversationRef.current = false;
        
        requestAnimationFrame(() => {
          if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
          }
        });
      }
    }, [streamingContent, streamingThought, isStreaming]);

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
        setShowLoadingIndicator(false);
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

    // Determine states
    const shouldShowLoading =
      (propIsLoadingEarlier && hasEarlierMessages) || (showLoadingIndicator && hasEarlierMessages);
    const showLoadingState = isLoading && timeline.length === 0;
    const showEmptyState = !isLoading && timeline.length === 0;

    // Virtualizer setup
    const estimateSize = useCallback(
      (index: number) => estimateGroupedItemHeight(groupedItems[index]),
      [groupedItems]
    );

    const virtualizer = useVirtualizer({
      count: groupedItems.length,
      getScrollElement: () => containerRef.current,
      estimateSize,
      overscan: 10,
    });

    // Reset scroll state and virtualizer when conversation changes
    useEffect(() => {
      if (lastConversationIdRef.current === conversationId) return;
      lastConversationIdRef.current = conversationId;

      isSwitchingConversationRef.current = true;

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
          }
          isInitialLoadRef.current = false;
          hasScrolledInitiallyRef.current = true;
          prevTimelineLengthRef.current = timeline.length;
          isSwitchingConversationRef.current = false;
        });
        cleanupRef.current = rafId2;
      });
      // Store inner rAF id for cleanup
      const cleanupRef = { current: 0 as number };

      return () => {
        cancelAnimationFrame(rafId);
        if (cleanupRef.current) cancelAnimationFrame(cleanupRef.current);
      };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [conversationId]);

    // j/k keyboard navigation for messages
    const focusedMsgRef = useRef<number>(-1);
    const [focusedMsgIndex, setFocusedMsgIndex] = useState(-1);

    // Build navigable indices (user_message and assistant_message only)
    const navigableIndices = useCallback(() => {
      const indices: number[] = [];
      groupedItems.forEach((item, idx) => {
        if (item.kind === 'event') {
          const t = item.event.type;
          if (t === 'user_message' || t === 'assistant_message') {
            indices.push(idx);
          }
        }
      });
      return indices;
    }, [groupedItems]);

    useEffect(() => {
      focusedMsgRef.current = focusedMsgIndex;
    }, [focusedMsgIndex]);

    useEffect(() => {
      const handleNav = (e: KeyboardEvent) => {
        const target = e.target as HTMLElement;
        const isInput =
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable;
        if (isInput) return;

        if (e.key === 'j' || e.key === 'k') {
          e.preventDefault();
          const indices = navigableIndices();
          if (indices.length === 0) return;

          const current = focusedMsgRef.current;
          let currentPos = indices.indexOf(current);

          if (e.key === 'j') {
            currentPos = currentPos < indices.length - 1 ? currentPos + 1 : currentPos;
          } else {
            currentPos = currentPos > 0 ? currentPos - 1 : 0;
          }

          const nextIndex = indices[currentPos];
          setFocusedMsgIndex(nextIndex);

          // Scroll to the focused message
          const el = containerRef.current?.querySelector(
            `[data-msg-index="${nextIndex}"]`
          );
          if (el) {
            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        }

        // c to copy focused message content
        if (e.key === 'c' && focusedMsgRef.current >= 0) {
          const item = groupedItems[focusedMsgRef.current];
          if (item?.kind === 'event') {
            const ev = item.event;
            if (ev.type === 'user_message' || ev.type === 'assistant_message') {
              navigator.clipboard.writeText(ev.content).catch(() => {});
            }
          }
        }

        // Escape to clear focus
        if (e.key === 'Escape' && focusedMsgRef.current >= 0) {
          setFocusedMsgIndex(-1);
        }
      };

      window.addEventListener('keydown', handleNav);
      return () => window.removeEventListener('keydown', handleNav);
    }, [navigableIndices, groupedItems]);

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
                <LoadingOutlined className="text-primary mr-2" spin />
                <span className="text-xs text-slate-500">
                  {scrollIndicatorChild?.props?.label || 'Loading...'}
                </span>
              </div>
            </div>
          )}

          {/* Pinned Messages Section */}
          {pinnedEvents.length > 0 && (
            <div className="flex-shrink-0 border-b border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-800/50">
              <button
                type="button"
                onClick={() => setPinnedCollapsed(!pinnedCollapsed)}
                className="flex items-center gap-2 w-full px-4 py-2 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
              >
                <Pin size={12} />
                <span>{t('agent.pinnedMessages', 'Pinned')}</span>
                <span className="text-slate-400">({pinnedEvents.length})</span>
                <span className="ml-auto">
                  {pinnedCollapsed ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
                </span>
              </button>
              {!pinnedCollapsed && (
                <div className="px-4 pb-2 space-y-1.5 max-h-40 overflow-y-auto">
                  {pinnedEvents.map((event) => {
                    const content =
                      ('content' in event ? (event as any).content : '') ||
                      ('fullText' in event ? (event as any).fullText : '');
                    return (
                      <div
                        key={`pinned-${event.id}`}
                        className="flex items-start gap-2 px-3 py-2 bg-white dark:bg-slate-800 rounded-lg border border-slate-200/80 dark:border-slate-700/50 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/60 transition-colors group/pin"
                        onClick={() => {
                          const el = containerRef.current?.querySelector(
                            `[data-msg-id="${event.id}"]`
                          );
                          if (el) {
                            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
                          }
                        }}
                      >
                        <p className="flex-1 text-xs text-slate-600 dark:text-slate-300 line-clamp-2 leading-relaxed">
                          {content || '...'}
                        </p>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (event.id) togglePinEvent(event.id);
                          }}
                          className="flex-shrink-0 p-1 rounded text-slate-400 hover:text-red-500 opacity-0 group-hover/pin:opacity-100 transition-opacity"
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
              className="flex-1 overflow-y-auto chat-scrollbar p-4 md:p-6 pb-24 min-h-0"
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
                  if (item.kind === 'timeline') {
                    return (
                      <div
                        key={`timeline-group-${item.startIndex}`}
                        data-index={virtualRow.index}
                        data-msg-index={virtualRow.index}
                        ref={virtualizer.measureElement}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                      >
                        <div className="flex items-start gap-3 mb-3">
                          <div className="w-8 shrink-0" />
                          <div className="flex-1 min-w-0 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
                            <ExecutionTimeline
                              steps={item.steps}
                              isStreaming={isStreaming && item.startIndex + item.steps.length >= timeline.length}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  }
                  const { event, index } = item;
                  const isFocused = focusedMsgIndex === virtualRow.index;
                  return (
                    <div
                      key={event.id || `event-${index}`}
                      data-index={virtualRow.index}
                      data-msg-index={virtualRow.index}
                      data-msg-id={event.id}
                      ref={virtualizer.measureElement}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                      className={isFocused ? 'ring-2 ring-blue-400/60 dark:ring-blue-500/50 rounded-xl transition-shadow duration-200' : ''}
                    >
                      <div className="pb-3">
                        <MessageBubble
                          event={event}
                          isStreaming={isStreaming && index === timeline.length - 1}
                          allEvents={timeline}
                          isPinned={!!event.id && pinnedEventIds.has(event.id)}
                          onPin={event.id ? () => togglePinEvent(event.id!) : undefined}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Non-virtualized streaming/footer content */}
              <div className="space-y-3">
                {/* Suggestion chips - shown when not streaming and suggestions available */}
                {!isStreaming && suggestions && suggestions.length > 0 && onSuggestionSelect && (
                  <SuggestionChips
                    suggestions={suggestions}
                    onSelect={onSuggestionSelect}
                  />
                )}

                {/* Plan progress bar for multi-step plans */}
                {isStreaming && <PlanProgressBar className="mb-4" />}

                {/* Agent state transition pill */}
                {isStreaming && <AgentStatePill className="mb-4" />}

                {/* Streaming thought indicator - ThinkingBlock (new design) */}
                {includeStreamingContent && (isThinkingStreaming || streamingThought) && (
                  <ThinkingBlock
                    content={streamingThought || ''}
                    isStreaming={!!isThinkingStreaming}
                  />
                )}

                {/* Streaming tool preparation indicator */}
                {includeStreamingContent && isStreaming && <StreamingToolPreparation />}

                {/* Streaming content indicator - matches MessageBubble.Assistant style */}
                {includeStreamingContent &&
                  isStreaming &&
                  streamingContent &&
                  !isThinkingStreaming && (
                    <div className="flex items-start gap-3 mb-6 animate-fade-in-up" aria-live="assertive">
                      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center flex-shrink-0 shadow-sm shadow-primary/20">
                        <svg
                          className="w-[18px] h-[18px] text-white"
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
                      <div className="flex-1 max-w-[85%] md:max-w-[75%] lg:max-w-[70%]">
                        <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/50 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm">
                          <div className={MARKDOWN_PROSE_CLASSES}>
                            <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
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
