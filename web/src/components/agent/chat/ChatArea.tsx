
import React, { memo, useMemo, useRef, useEffect, useCallback } from "react";
import { Spin } from "antd";
import {
  IdleState,
  type StarterTile,
} from "./IdleState";
import {
  MessageStream,
  UserMessage,
  AgentSection,
  ReasoningLogCard,
  ToolExecutionCardDisplay,
} from "./MessageStream";
import { AssistantMessage } from "./AssistantMessage";
import { ExecutionTimeline } from "../execution/ExecutionTimeline";
import { FollowUpPills } from "../execution/FollowUpPills";
import { PlanModeIndicator } from "../PlanModeIndicator";
import { PlanEditor } from "../PlanEditor";
import type { WorkPlan, ToolExecution, TimelineStep, PlanDocument, PlanModeStatus } from "../../../types/agent";

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

function shouldShowExecutionPlan(
  workPlan: WorkPlan | null | undefined,
  executionTimeline: TimelineStep[],
  toolExecutionHistory: ToolExecution[]
): boolean {
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
  messages: any[];
  currentConversation: any;
  isStreaming: boolean;
  messagesLoading: boolean;
  currentWorkPlan: WorkPlan | null;
  currentStepNumber: number | null;
  currentThought: string | null;
  currentToolCall: any;
  executionTimeline: TimelineStep[];
  toolExecutionHistory: ToolExecution[];
  matchedPattern: any;
  planModeStatus: PlanModeStatus | null;
  showPlanEditor: boolean;
  currentPlan: PlanDocument | null;
  planLoading: boolean;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  onViewPlan: () => void;
  onExitPlanMode: (approve: boolean) => Promise<void>;
  onUpdatePlan: (content: string) => Promise<void>;
  onSend: (message: string) => void;
  onTileClick: (tile: StarterTile) => void;
  // Typewriter streaming state
  assistantDraftContent?: string;
  isTextStreaming?: boolean;
  // Pagination state
  hasEarlierMessages?: boolean;
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
    prevProps.messages !== nextProps.messages ||
    prevProps.currentConversation?.id !== nextProps.currentConversation?.id ||
    prevProps.isStreaming !== nextProps.isStreaming ||
    prevProps.messagesLoading !== nextProps.messagesLoading ||
    prevProps.assistantDraftContent !== nextProps.assistantDraftContent ||
    prevProps.isTextStreaming !== nextProps.isTextStreaming;

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
    prevProps.currentThought === nextProps.currentThought &&
    prevProps.currentWorkPlan?.current_step_index === nextProps.currentWorkPlan?.current_step_index &&
    prevProps.executionTimeline.length === nextProps.executionTimeline.length &&
    prevProps.toolExecutionHistory.length === nextProps.toolExecutionHistory.length
  );
}

export const ChatArea: React.FC<ChatAreaProps> = memo(({
  messages,
  currentConversation,
  isStreaming,
  messagesLoading,
  currentWorkPlan,
  currentStepNumber,
  currentThought,
  currentToolCall,
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
  assistantDraftContent,
  isTextStreaming,
}) => {
  // Memoize sorted messages to avoid re-sorting on every render
  const sortedMessages = useMemo(
    () =>
      [...messages].sort(
        (a, b) =>
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      ),
    [messages]
  );

  // Scroll handling for backward pagination
  const isLoadingEarlierRef = useRef(false);
  const previousScrollHeightRef = useRef(0);

  const handleScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      const target = e.target as HTMLDivElement;
      const { scrollTop, scrollHeight, clientHeight } = target;

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
           messages.length === 0 && 
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

        {/* Active Chat - Show when there are messages OR when streaming (even if no messages yet) */}
        {currentConversation && (messages.length > 0 || isStreaming) && (
          <div className="py-6 space-y-6">
            <MessageStream>
              {sortedMessages.map((message, index, arr) => {
                  if (message.role === "user") {
                    const isLastUserMessage = !arr
                      .slice(index + 1)
                      .some((m) => m.role === "user");

                    const shouldShowRealtimeTimeline =
                      isLastUserMessage &&
                      isStreaming &&
                      shouldShowExecutionPlan(
                        currentWorkPlan,
                        executionTimeline,
                        toolExecutionHistory
                      );

                    const nextMessage = arr[index + 1];
                    const hasHistoricalToolData =
                      nextMessage?.role === "assistant" &&
                      ((nextMessage.tool_calls &&
                        nextMessage.tool_calls.length > 0) ||
                        nextMessage.metadata?.work_plan);

                    const historicalWorkPlan =
                      hasHistoricalToolData &&
                      nextMessage?.metadata?.work_plan
                        ? (nextMessage.metadata.work_plan as WorkPlan)
                        : null;

                    const historicalToolExecutions: ToolExecution[] =
                      hasHistoricalToolData && nextMessage?.tool_calls
                        ? nextMessage.tool_calls.map(
                            (tc: any, idx: number) => {
                              const toolResult =
                                nextMessage.tool_results?.find(
                                  (r: any) => r.tool_name === tc.name
                                );
                              return {
                                id: `${nextMessage.id}-tool-${idx}`,
                                toolName: tc.name,
                                input: tc.arguments || {},
                                result: toolResult?.result || undefined,
                                error: toolResult?.error || undefined,
                                status: (toolResult && !toolResult.error
                                  ? "success"
                                  : toolResult?.error
                                  ? "failed"
                                  : "success") as ToolExecution["status"],
                                startTime: nextMessage.created_at,
                                endTime: nextMessage.created_at,
                                duration: 0,
                              };
                            }
                          )
                        : [];

                    const historicalSteps: TimelineStep[] =
                      historicalWorkPlan?.steps?.map((step, idx) => ({
                        stepNumber: step.step_number ?? idx + 1,
                        description: step.description,
                        status: "completed" as const,
                        thoughts: [],
                        toolExecutions: [],
                      })) ?? [];

                    const shouldShowHistoricalTimeline =
                      !isStreaming &&
                      isLastUserMessage &&
                      shouldShowExecutionPlan(
                        historicalWorkPlan || currentWorkPlan,
                        historicalSteps.length > 0
                          ? historicalSteps
                          : executionTimeline,
                        historicalToolExecutions.length > 0
                          ? historicalToolExecutions
                          : toolExecutionHistory
                      );

                    return (
                      <div key={message.id} className="animate-fade-in-up">
                        <UserMessage content={message.content} />
                        {shouldShowRealtimeTimeline && (
                          <div className="mt-4">
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
                        {shouldShowHistoricalTimeline && (
                          <div className="mt-4">
                            <ExecutionTimeline
                              workPlan={historicalWorkPlan || currentWorkPlan}
                              steps={
                                historicalSteps.length > 0
                                  ? historicalSteps
                                  : executionTimeline
                              }
                              toolExecutionHistory={
                                historicalToolExecutions.length > 0
                                  ? historicalToolExecutions
                                  : toolExecutionHistory
                              }
                              isStreaming={false}
                              currentStepNumber={
                                historicalWorkPlan?.steps?.length ??
                                currentStepNumber
                              }
                              matchedPattern={matchedPattern}
                            />
                          </div>
                        )}
                      </div>
                    );
                  }

                  const hasExecutionData =
                    message.tool_calls && message.tool_calls.length > 0;
                  const hasWorkPlan = message.metadata?.work_plan;
                  const isLastMessage = index === arr.length - 1;

                  return (
                    <div key={message.id} className="space-y-4 animate-slide-up">
                      {hasWorkPlan
                        ? (() => {
                            const workPlanData = message.metadata
                              ?.work_plan as
                              | { steps?: Array<{ description: string }> }
                              | undefined;
                            return (
                              <AgentSection
                                icon="psychology"
                                opacity={true}
                              >
                                <ReasoningLogCard
                                  steps={
                                    workPlanData?.steps?.map(
                                      (s) => s.description
                                    ) || []
                                  }
                                  summary={`Work Plan: ${
                                    workPlanData?.steps?.length || 0
                                  } steps`}
                                  completed={true}
                                  expanded={false}
                                />
                              </AgentSection>
                            );
                          })()
                        : null}

                      {hasExecutionData &&
                        message.tool_calls?.map(
                          (toolCall: any, idx: number) => {
                            const correspondingResult =
                              message.tool_results?.find(
                                (r: any) =>
                                  r.tool_call_id === toolCall.call_id
                              );
                            return (
                              <AgentSection
                                key={`${message.id}-tool-${idx}`}
                                icon="construction"
                                iconBg="bg-slate-200 dark:bg-border-dark"
                                opacity={true}
                              >
                                <ToolExecutionCardDisplay
                                  toolName={toolCall.name}
                                  status={
                                    correspondingResult &&
                                    !correspondingResult.error
                                      ? "success"
                                      : correspondingResult?.error
                                      ? "error"
                                      : "running"
                                  }
                                  parameters={toolCall.arguments}
                                />
                              </AgentSection>
                            );
                          }
                        )}

                      <AssistantMessage
                        content={message.content}
                        isReport={message.metadata?.isReport === true}
                        generatedAt={message.created_at}
                      />
                      {isLastMessage && !isStreaming && (
                        <div className="ml-11 mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                          <FollowUpPills
                            suggestions={MOCK_SUGGESTIONS}
                            onSuggestionClick={onSend}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}

              {currentThought && executionTimeline.length === 0 && (
                <AgentSection icon="psychology">
                  <ReasoningLogCard
                    steps={[currentThought]}
                    summary="Thinking..."
                    completed={false}
                    expanded={true}
                  />
                </AgentSection>
              )}

              {currentToolCall &&
                executionTimeline.length === 0 &&
                toolExecutionHistory.length === 0 && (
                  <AgentSection
                    icon="construction"
                    iconBg="bg-slate-200 dark:bg-border-dark"
                  >
                    <ToolExecutionCardDisplay
                      toolName={currentToolCall.name}
                      status="running"
                      parameters={currentToolCall.input}
                    />
                  </AgentSection>
                )}

              {/* Typewriter streaming draft content */}
              {isTextStreaming && assistantDraftContent && (
                <div className="animate-fade-in">
                  <AssistantMessage
                    content={assistantDraftContent}
                    isReport={false}
                  />
                </div>
              )}
            </MessageStream>
          </div>
        )}
      </div>
      <div ref={messagesEndRef} className="h-4" />
    </div>
  );
}, areChatAreaPropsEqual);

ChatArea.displayName = "ChatArea";
