/**
 * ChatArea - Unified chat message display component
 *
 * Refactored to use TimelineEventRenderer for consistent rendering
 * of both streaming and historical messages.
 *
 * @module components/agent/chat/ChatArea
 */

import React, { memo, useMemo, useRef, useEffect, useCallback } from "react";
import { Spin } from "antd";
import {
  IdleState,
  type StarterTile,
} from "./IdleState";
import { TimelineEventRenderer } from "./TimelineEventRenderer";
import { ExecutionTimeline } from "../execution/ExecutionTimeline";
import { FollowUpPills } from "../execution/FollowUpPills";
import { PlanModeIndicator } from "../PlanModeIndicator";
import { PlanEditor } from "../PlanEditor";
import type { WorkPlan, ToolExecution, TimelineStep, PlanDocument, PlanModeStatus, TimelineEvent } from "../../../types/agent";

// Default starter tiles
const DEFAULT_STARTER_TILES: StarterTile[] = [
  {
    id: "trends",
    title: "Analyze project trends",
    description: "Identify key patterns across multiple data streams",
    color: "blue",
    icon: "analytics",
  },
  {
    id: "reports",
    title: "Synthesize Q4 reports",
    description: "Aggregate complex findings into an executive summary",
    color: "purple",
    icon: "summarize",
  },
  {
    id: "audit",
    title: "Audit memory logs",
    description: "Review system activity and trace data genealogy",
    color: "emerald",
    icon: "verified_user",
  },
  {
    id: "compare",
    title: "Cross-project comparison",
    description: "Compare performance metrics between active projects",
    color: "amber",
    icon: "compare_arrows",
  },
];

const MOCK_SUGGESTIONS = [
  "Compare with competitors?",
  "Drill down into details",
  "Export as PDF",
  "Analyze related trends",
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
}

/**
 * Custom comparison function for ChatArea memo
 * Prevents unnecessary re-renders by only checking props that actually affect rendering
 */
function areChatAreaPropsEqual(
  prevProps: ChatAreaProps,
  nextProps: ChatAreaProps
): boolean {
  // Props that always trigger re-render
  const criticalPropsChanged =
    prevProps.timeline !== nextProps.timeline ||
    prevProps.currentConversation?.id !== nextProps.currentConversation?.id ||
    prevProps.isStreaming !== nextProps.isStreaming ||
    prevProps.messagesLoading !== nextProps.messagesLoading;

  if (criticalPropsChanged) {
    return false;
  }

  // Props that can trigger re-render but less frequently
  const secondaryPropsChanged =
    prevProps.planModeStatus?.is_in_plan_mode !== nextProps.planModeStatus?.is_in_plan_mode ||
    prevProps.showPlanEditor !== nextProps.showPlanEditor ||
    prevProps.currentPlan?.id !== nextProps.currentPlan?.id;

  if (secondaryPropsChanged) {
    return false;
  }

  // For the remaining props, use shallow comparison
  return (
    prevProps.currentStepNumber === nextProps.currentStepNumber &&
    prevProps.currentWorkPlan?.current_step_index === nextProps.currentWorkPlan?.current_step_index &&
    prevProps.executionTimeline.length === nextProps.executionTimeline.length &&
    prevProps.toolExecutionHistory.length === nextProps.toolExecutionHistory.length
  );
}

export const ChatArea: React.FC<ChatAreaProps> = memo(({
  timeline,
  currentConversation,
  isStreaming,
  messagesLoading,
  currentWorkPlan,
  currentStepNumber,
  executionTimeline,
  toolExecutionHistory,
  matchedPattern,
  planModeStatus,
  showPlanEditor,
  currentPlan,
  planLoading,
  scrollContainerRef,
  messagesEndRef,
  onViewPlan,
  onExitPlanMode,
  onUpdatePlan,
  onSend,
  onTileClick,
  hasEarlierMessages,
  onLoadEarlier,
}) => {
  // Memoize sorted timeline events (they should already be sorted by sequence)
  const sortedTimeline = useMemo(
    () =>
      [...timeline].sort(
        (a, b) => a.sequenceNumber - b.sequenceNumber
      ),
    [timeline]
  );

  // Determine if rich ExecutionTimeline should be shown
  const showRichTimeline = shouldShowRichExecutionTimeline(
    currentWorkPlan,
    executionTimeline,
    toolExecutionHistory
  );

  // Scroll handling for backward pagination
  const isLoadingEarlierRef = useRef(false);
  const previousScrollHeightRef = useRef(0);

  const handleScroll = useCallback(
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

  // Restore scroll position after loading earlier messages
  useEffect(() => {
    if (!messagesLoading && previousScrollHeightRef.current > 0 && scrollContainerRef.current) {
      const scrollContainer = scrollContainerRef.current;
      const newScrollHeight = scrollContainer.scrollHeight;
      const scrollOffset = newScrollHeight - previousScrollHeightRef.current;

      scrollContainer.scrollTop = scrollOffset;
      previousScrollHeightRef.current = 0;
    }
  }, [messagesLoading]);

  return (
    <div
      ref={scrollContainerRef}
      className="flex-1 overflow-y-auto px-4 pt-6 scroll-smooth"
      onScroll={handleScroll}
    >
      <div className="max-w-4xl mx-auto">
        {/* Loading indicator for earlier messages */}
        {messagesLoading && hasEarlierMessages && (
          <div className="flex justify-center py-2">
            <Spin size="small" />
            <span className="ml-2 text-sm text-slate-500">加载历史消息...</span>
          </div>
        )}
        {/* Plan Mode Indicator */}
        {planModeStatus && (
          <PlanModeIndicator
            status={planModeStatus}
            onViewPlan={onViewPlan}
            onExitPlanMode={async () => onExitPlanMode(false)}
          />
        )}

        {/* Plan Editor Modal */}
        {showPlanEditor && currentPlan && (
          <div className="mb-6 animate-fade-in">
            <PlanEditor
              plan={currentPlan}
              isLoading={planLoading}
              onUpdate={onUpdatePlan}
              onExit={onExitPlanMode}
              readOnly={false}
            />
            <button
              onClick={async () => onExitPlanMode(false)}
              className="mt-2 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
            >
              Hide Plan Editor
            </button>
          </div>
        )}

        {/* Idle State - Only show when truly idle (not streaming, not loading messages) */}
        {(!currentConversation ||
          (currentConversation &&
           sortedTimeline.length === 0 &&
           !isStreaming &&
           !messagesLoading)) && (
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
        )}

        {/* Active Chat - Show when there are timeline events OR when streaming */}
        {currentConversation && (sortedTimeline.length > 0 || isStreaming) && (
          <div className="py-6 space-y-6">
            {/* Show rich ExecutionTimeline for complex multi-step execution during streaming */}
            {showRichTimeline && isStreaming && (
              <div className="mb-4">
                <ExecutionTimeline
                  workPlan={currentWorkPlan}
                  steps={executionTimeline}
                  toolExecutionHistory={toolExecutionHistory}
                  isStreaming={isStreaming}
                  currentStepNumber={currentStepNumber}
                  matchedPattern={matchedPattern}
                />
              </div>
            )}

            {/* Unified TimelineEventRenderer for consistent message display */}
            <TimelineEventRenderer
              events={sortedTimeline}
              isStreaming={isStreaming}
              showExecutionDetails={true}
            />

            {/* Follow-up suggestions after conversation ends */}
            {!isStreaming && sortedTimeline.length > 0 && (
              <div className="ml-11 mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                <FollowUpPills
                  suggestions={MOCK_SUGGESTIONS}
                  onSuggestionClick={onSend}
                />
              </div>
            )}
          </div>
        )}
      </div>
      <div ref={messagesEndRef} className="h-4" />
    </div>
  );
}, areChatAreaPropsEqual);

ChatArea.displayName = "ChatArea";
