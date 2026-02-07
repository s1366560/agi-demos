/**
 * ChatArea - Unified chat message display component
 *
 * Uses VirtualTimelineEventList for efficient rendering
 * with timeline mode - each event displayed independently in chronological order.
 *
 * @module components/agent/chat/ChatArea
 */

import React, { memo, useMemo } from 'react';

import { Spin } from 'antd';

import { ExecutionTimeline } from '../execution/ExecutionTimeline';
import { FollowUpPills } from '../execution/FollowUpPills';
import { VirtualTimelineEventList } from '../VirtualTimelineEventList';

import { IdleState, type StarterTile } from './IdleState';

import type {
  WorkPlan,
  ToolExecution,
  TimelineStep,
  PlanDocument,
  PlanModeStatus,
  TimelineEvent,
} from '../../../types/agent';

// Default starter tiles
const DEFAULT_STARTER_TILES: StarterTile[] = [
  {
    id: 'trends',
    title: 'Analyze project trends',
    description: 'Identify key patterns across multiple data streams',
    color: 'blue',
    icon: 'analytics',
  },
  {
    id: 'reports',
    title: 'Synthesize Q4 reports',
    description: 'Aggregate complex findings into an executive summary',
    color: 'purple',
    icon: 'summarize',
  },
  {
    id: 'audit',
    title: 'Audit memory logs',
    description: 'Review system activity and trace data genealogy',
    color: 'emerald',
    icon: 'verified_user',
  },
  {
    id: 'compare',
    title: 'Cross-project comparison',
    description: 'Compare performance metrics between active projects',
    color: 'amber',
    icon: 'compare_arrows',
  },
];

const MOCK_SUGGESTIONS = [
  'Compare with competitors?',
  'Drill down into details',
  'Export as PDF',
  'Analyze related trends',
];

/**
 * Determine if the rich ExecutionTimeline should be shown
 * (for active streaming with complex multi-step execution)
 */
function shouldShowRichExecutionTimeline(
  workPlan: WorkPlan | null | undefined,
  executionTimeline: TimelineStep[],
  toolExecutionHistory: ToolExecution[]
): boolean {
  // Show rich timeline only for complex multi-step work plans during streaming
  if (workPlan && workPlan.steps && workPlan.steps.length > 1) {
    return true;
  }
  if (toolExecutionHistory.length > 1) {
    return true;
  }
  if (executionTimeline.length > 1) {
    return true;
  }
  return false;
}

interface ChatAreaProps {
  /** Timeline events (unified event stream) */
  timeline: TimelineEvent[];
  /** Current conversation */
  currentConversation: any;
  /** Whether agent is currently streaming */
  isStreaming: boolean;
  /** Whether timeline messages are loading */
  messagesLoading: boolean;
  /** Current work plan (for rich timeline display) */
  currentWorkPlan: WorkPlan | null;
  /** Current step number */
  currentStepNumber: number | null;
  /** Execution timeline (for rich timeline display) */
  executionTimeline: TimelineStep[];
  /** Tool execution history */
  toolExecutionHistory: ToolExecution[];
  /** Matched workflow pattern */
  matchedPattern: any;
  /** Plan mode status */
  planModeStatus: PlanModeStatus | null;
  /** Whether to show plan editor */
  showPlanEditor: boolean;
  /** Current plan document */
  currentPlan: PlanDocument | null;
  /** Whether plan is loading */
  planLoading: boolean;
  /** Scroll container ref */
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  /** Messages end ref (for auto-scroll) */
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  /** View plan callback */
  onViewPlan: () => void;
  /** Exit plan mode callback */
  onExitPlanMode: (approve: boolean) => Promise<void>;
  /** Update plan callback */
  onUpdatePlan: (content: string) => Promise<void>;
  /** Send message callback */
  onSend: (message: string) => void;
  /** Starter tile click callback */
  onTileClick: (tile: StarterTile) => void;
  /** Pagination: has earlier messages to load */
  hasEarlierMessages?: boolean;
  /** Pagination: load earlier messages callback */
  onLoadEarlier?: () => void;
  /** Streaming content for real-time display */
  streamingContent?: string;
  /** Streaming thought for real-time display */
  streamingThought?: string;
  /** Whether thinking is currently streaming */
  isThinkingStreaming?: boolean;
}

/**
 * Custom comparison function for ChatArea memo
 * Prevents unnecessary re-renders by only checking props that actually affect rendering
 */
function areChatAreaPropsEqual(prevProps: ChatAreaProps, nextProps: ChatAreaProps): boolean {
  // Props that always trigger re-render
  const criticalPropsChanged =
    prevProps.timeline !== nextProps.timeline ||
    prevProps.currentConversation?.id !== nextProps.currentConversation?.id ||
    prevProps.isStreaming !== nextProps.isStreaming ||
    prevProps.messagesLoading !== nextProps.messagesLoading ||
    prevProps.streamingContent !== nextProps.streamingContent ||
    prevProps.streamingThought !== nextProps.streamingThought ||
    prevProps.isThinkingStreaming !== nextProps.isThinkingStreaming;

  if (criticalPropsChanged) {
    return false;
  }

  // For the remaining props, use shallow comparison
  return (
    prevProps.currentStepNumber === nextProps.currentStepNumber &&
    prevProps.currentWorkPlan?.current_step_index ===
      nextProps.currentWorkPlan?.current_step_index &&
    prevProps.executionTimeline.length === nextProps.executionTimeline.length &&
    prevProps.toolExecutionHistory.length === nextProps.toolExecutionHistory.length
  );
}

export const ChatArea: React.FC<ChatAreaProps> = memo(
  ({
    timeline,
    currentConversation,
    isStreaming,
    messagesLoading,
    currentWorkPlan,
    currentStepNumber,
    executionTimeline,
    toolExecutionHistory,
    matchedPattern,
    planModeStatus: _planModeStatus,
    showPlanEditor: _showPlanEditor,
    currentPlan: _currentPlan,
    planLoading: _planLoading,
    scrollContainerRef,
    messagesEndRef: _messagesEndRef,
    onViewPlan: _onViewPlan,
    onExitPlanMode: _onExitPlanMode,
    onUpdatePlan: _onUpdatePlan,
    onSend,
    onTileClick,
    hasEarlierMessages,
    onLoadEarlier,
    streamingContent,
    streamingThought,
    isThinkingStreaming,
  }) => {
    // Memoize sorted timeline events (they should already be sorted by sequence)
    const sortedTimeline = useMemo(
      () => [...timeline].sort((a, b) => a.sequenceNumber - b.sequenceNumber),
      [timeline]
    );

    // Determine if rich ExecutionTimeline should be shown
    const showRichTimeline = shouldShowRichExecutionTimeline(
      currentWorkPlan,
      executionTimeline,
      toolExecutionHistory
    );

    // Scroll handling for backward pagination
    // TODO: Apply this scroll handler to the scroll container for backward pagination
    /*
  const isLoadingEarlierRef = useRef(false);
  const previousScrollHeightRef = useRef(0);

  const _handleScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      const target = e.target as HTMLDivElement;
      const { scrollTop, scrollHeight } = target;

      // When scrolling to near the top, trigger load more
      const SCROLL_THRESHOLD = 50;

      if (
        scrollTop < SCROLL_THRESHOLD &&
        !isLoadingEarlierRef.current &&
        !messagesLoading &&
        currentConversation &&
        hasEarlierMessages &&
        onLoadEarlier
      ) {
        isLoadingEarlierRef.current = true;
        previousScrollHeightRef.current = scrollHeight;

        onLoadEarlier();

        // Reset loading flag after a short delay
        setTimeout(() => {
          isLoadingEarlierRef.current = false;
        }, 500);
      }
    },
    [messagesLoading, currentConversation, hasEarlierMessages, onLoadEarlier]
  );
  */

    // Restore scroll position after loading earlier messages
    // TODO: Enable when backward pagination is implemented
    /*
  const previousScrollHeightRef = useRef(0);
  useEffect(() => {
    if (!messagesLoading && previousScrollHeightRef.current > 0 && scrollContainerRef.current) {
      const scrollContainer = scrollContainerRef.current;
      const newScrollHeight = scrollContainer.scrollHeight;
      const scrollOffset = newScrollHeight - previousScrollHeightRef.current;

      scrollContainer.scrollTop = scrollOffset;
      previousScrollHeightRef.current = 0;
    }
  }, [messagesLoading, scrollContainerRef]);
  */

    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Loading indicator for earlier messages - 更加低调的样式 */}
        {messagesLoading && hasEarlierMessages && (
          <div className="absolute top-2 left-0 right-0 z-10 flex justify-center pointer-events-none">
            <div className="flex items-center px-3 py-1.5 bg-slate-100/90 dark:bg-slate-800/90 backdrop-blur-sm rounded-full shadow-sm border border-slate-200/50 dark:border-slate-700/50 opacity-70">
              <Spin size="small" />
              <span className="ml-2 text-xs text-slate-500">Loading...</span>
            </div>
          </div>
        )}

        {/* Main content area */}
        <div className="flex-1 overflow-hidden">
          {/* Idle State - Only show when truly idle (not streaming, not loading messages) */}
          {(!currentConversation ||
            (currentConversation &&
              sortedTimeline.length === 0 &&
              !isStreaming &&
              !messagesLoading)) && (
            <div
              ref={scrollContainerRef}
              className="h-full overflow-y-auto px-4 pt-6 scroll-smooth chat-messages"
            >
              <div className="w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto">
                <div className="flex flex-col items-center justify-center min-h-full py-12 animate-fade-in">
                  <div className="w-full text-center space-y-12">
                    <IdleState
                      greeting="How can I help you today?"
                      subtitle="Access your intelligent memory workspace. Start a conversation or select a suggested task below."
                      starterTiles={DEFAULT_STARTER_TILES}
                      onTileClick={onTileClick}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Active Chat - Show when there are timeline events OR when streaming */}
          {currentConversation && (sortedTimeline.length > 0 || isStreaming) && (
            <div className="h-full flex flex-col">
              {/* Rich ExecutionTimeline for complex multi-step execution during streaming */}
              {showRichTimeline && isStreaming && (
                <div className="px-4 py-2 bg-slate-50 dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-800">
                  <div className="w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto">
                    <ExecutionTimeline
                      workPlan={currentWorkPlan}
                      steps={executionTimeline}
                      toolExecutionHistory={toolExecutionHistory}
                      isStreaming={isStreaming}
                      currentStepNumber={currentStepNumber}
                      matchedPattern={matchedPattern}
                    />
                  </div>
                </div>
              )}

              {/* Virtualized Timeline Event List */}
              <div className="flex-1 overflow-hidden">
                <VirtualTimelineEventList
                  timeline={sortedTimeline}
                  isStreaming={isStreaming}
                  className="chat-messages"
                  hasEarlierMessages={hasEarlierMessages}
                  isLoadingEarlier={messagesLoading && hasEarlierMessages}
                  onLoadEarlier={onLoadEarlier}
                  conversationId={currentConversation?.id}
                  streamingContent={streamingContent}
                  streamingThought={streamingThought}
                  isThinkingStreaming={isThinkingStreaming}
                />
              </div>

              {/* Follow-up suggestions after conversation ends */}
              {!isStreaming && sortedTimeline.length > 0 && (
                <div className="px-4 py-4 bg-white dark:bg-slate-900 border-t border-slate-100 dark:border-slate-800">
                  <div className="w-full max-w-3xl lg:max-w-5xl xl:max-w-7xl mx-auto">
                    <FollowUpPills suggestions={MOCK_SUGGESTIONS} onSuggestionClick={onSend} />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  },
  areChatAreaPropsEqual
);

ChatArea.displayName = 'ChatArea';
