import React, { useEffect, useRef, useCallback, useState } from "react";
import { Message, ToolCall, ToolResult } from "../../types/agent";
import {
  MessageStream,
  UserMessage,
  AgentSection,
  ReasoningLogCard,
  ToolExecutionCardDisplay,
} from "./chat/MessageStream";
import { AssistantMessage } from "./chat/AssistantMessage";
import { useVirtualizer } from "@tanstack/react-virtual";

/**
 * Props for MessageList component
 */
interface MessageListProps {
  /** Array of messages to display */
  messages: Message[];
  /** Whether the agent is currently streaming a response */
  isStreaming: boolean;
  /** Current thought being processed (for streaming display) */
  currentThought?: string;
  /** Active tool calls from store (for realtime streaming) */
  activeToolCalls?: Map<
    string,
    ToolCall & { status: "running" | "success" | "failed"; startTime: number }
  >;
  /** Agent state for determining what to show */
  agentState?: "idle" | "thinking" | "acting" | "observing" | "awaiting_input";
}

/**
 * MessageList Component - Virtualized message display with auto-scroll
 *
 * Renders a list of chat messages with virtual scrolling for performance.
 * Supports streaming display of thoughts and tool executions in real-time.
 * Automatically scrolls to bottom during streaming, respects user scroll
 * position when scrolling up.
 *
 * @component
 *
 * @features
 * - Virtual scrolling for large conversation histories
 * - Auto-scroll to bottom during streaming
 * - Smart scroll detection (pauses auto-scroll when user scrolls up)
 * - Real-time display of thoughts and tool executions
 * - Timeline-based interleaved rendering
 * - Dynamic message height estimation
 * - Empty state with friendly message
 *
 * @example
 * ```tsx
 * import { MessageList } from '@/components/agent/MessageList'
 *
 * function ChatArea() {
 *   const { messages, isStreaming, currentThought } = useAgentV3Store()
 *
 *   return (
 *     <MessageList
 *       messages={messages}
 *       isStreaming={isStreaming}
 *       currentThought={currentThought}
 *       agentState="thinking"
 *     />
 *   )
 * }
 * ```
 */

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isStreaming,
  currentThought,
  activeToolCalls,
  agentState,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [containerHeight, setContainerHeight] = useState(600);
  const autoScrollRef = useRef(true);

  // Calculate container height on mount and resize
  useEffect(() => {
    const updateHeight = () => {
      const parent = scrollContainerRef.current?.parentElement;
      if (parent) {
        const height = parent.clientHeight - 32; // Account for padding
        setContainerHeight(Math.max(height, 200));
      }
    };

    updateHeight();
    window.addEventListener("resize", updateHeight);
    return () => window.removeEventListener("resize", updateHeight);
  }, []);

  // Track user scroll position to disable auto-scroll when user scrolls up
  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const handleScroll = () => {
      const isNearBottom =
        scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight < 100;
      autoScrollRef.current = isNearBottom;
    };

    scrollContainer.addEventListener("scroll", handleScroll);
    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, []);

  // Scroll to bottom when content changes (only if auto-scroll is enabled or streaming)
  useEffect(() => {
    if (!scrollContainerRef.current) return;

    if (autoScrollRef.current || isStreaming) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [
    messages.length,
    messages[messages.length - 1]?.content,
    currentThought,
    activeToolCalls?.size,
    isStreaming,
  ]);

  // Helper: Get tool result for a tool call
  const getToolResult = useCallback((toolName: string, toolResults?: ToolResult[]) => {
    return toolResults?.find((r) => r.tool_name === toolName);
  }, []);

  // Helper: Render a single thought card
  const renderSingleThought = useCallback((
    thought: string,
    idx: number,
    isThinking: boolean,
    isLast: boolean
  ) => {
    return (
      <AgentSection key={`thought-${idx}`} icon="psychology">
        <ReasoningLogCard
          steps={[thought]}
          summary={isThinking && isLast ? "Thinking..." : `Thought ${idx + 1}`}
          completed={!isThinking || !isLast}
          expanded={true}
        />
      </AgentSection>
    );
  }, []);

  // Helper: Render thoughts section (legacy - all in one card)
  const renderThoughts = useCallback((thoughts: string[], isThinking: boolean) => {
    if (thoughts.length === 0 && !isThinking) return null;

    return (
      <AgentSection icon="psychology">
        <ReasoningLogCard
          steps={thoughts}
          summary={isThinking ? "Thinking..." : `${thoughts.length} thoughts`}
          completed={!isThinking}
          expanded={isThinking || thoughts.length <= 3}
        />
      </AgentSection>
    );
  }, []);

  // Helper: Render tool executions for historical messages
  const renderHistoricalTools = useCallback((
    toolCalls: ToolCall[] | undefined,
    toolResults: ToolResult[] | undefined,
    toolExecutions:
      | Record<
          string,
          { startTime?: number; endTime?: number; duration?: number }
        >
      | undefined
  ) => {
    if (!toolCalls || toolCalls.length === 0) return null;

    return toolCalls.map((tool, idx) => {
      const result = getToolResult(tool.name, toolResults);
      const execution = toolExecutions?.[tool.name];
      const status = result ? (result.error ? "error" : "success") : "success";

      return (
        <AgentSection
          key={`tool-${idx}`}
          icon="construction"
          iconBg="bg-slate-200 dark:bg-border-dark"
          opacity={true}
        >
          <ToolExecutionCardDisplay
            toolName={tool.name}
            status={status}
            parameters={tool.arguments}
            duration={execution?.duration}
            result={result?.result}
            error={result?.error}
            defaultExpanded={false}
          />
        </AgentSection>
      );
    });
  }, [getToolResult]);

  // Helper: Render active tool calls (realtime streaming)
  const renderActiveTools = useCallback(() => {
    if (!activeToolCalls || activeToolCalls.size === 0) return null;

    return Array.from(activeToolCalls.entries()).map(([toolName, tool]) => {
      const displayStatus = tool.status === "failed" ? "error" : tool.status;

      return (
        <AgentSection
          key={`active-tool-${toolName}`}
          icon="construction"
          iconBg="bg-slate-200 dark:bg-border-dark"
        >
          <ToolExecutionCardDisplay
            toolName={toolName}
            status={displayStatus}
            parameters={tool.arguments}
            defaultExpanded={true}
          />
        </AgentSection>
      );
    });
  }, [activeToolCalls]);

  // Estimate message height for virtual scrolling
  const estimateMessageHeight = useCallback((msg: Message): number => {
    if (msg.role === "user") {
      return 80;
    }
    if (msg.role === "assistant") {
      const baseHeight = 200;
      const contentLines = msg.content?.split("\n").length || 0;
      const thoughtCount = (msg.metadata?.thoughts as string[])?.length || 0;
      const toolCallCount = msg.tool_calls?.length || 0;

      return (
        baseHeight +
        contentLines * 20 +
        thoughtCount * 60 +
        toolCallCount * 150
      );
    }
    return 60;
  }, []);

  // Get dynamic size for virtual row
  const getMessageSize = useCallback((index: number) => {
    return estimateMessageHeight(messages[index]);
  }, [messages, estimateMessageHeight]);

  // Set up virtual row virtualizer
  const rowVirtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollContainerRef.current,
    estimateSize: getMessageSize,
    overscan: 3,
  });

  const virtualRows = rowVirtualizer.getVirtualItems();
  const totalSize = rowVirtualizer.getTotalSize();

  // Render a single message
  const renderMessage = useCallback((msg: Message, index: number) => {
    const isLastMessage = index === messages.length - 1;
    const isLastAssistant = msg.role === "assistant" && isLastMessage;

    // User message
    if (msg.role === "user") {
      return (
        <div className="animate-fade-in-up pb-8">
          <UserMessage content={msg.content} />
        </div>
      );
    }

    // Assistant message - render execution flow + final response
    if (msg.role === "assistant") {
      const thoughts = (msg.metadata?.thoughts as string[]) || [];
      const timeline =
        (msg.metadata?.timeline as Array<{
          type: "thought" | "tool_call";
          id: string;
          content?: string;
          toolName?: string;
          toolInput?: any;
          timestamp: number;
        }>) || [];
      const toolExecutions = msg.metadata?.tool_executions as
        | Record<
            string,
            { startTime?: number; endTime?: number; duration?: number }
          >
        | undefined;

      const isActivelyStreaming = isLastAssistant && isStreaming;
      const isThinking =
        isActivelyStreaming &&
        (agentState === "thinking" || !!currentThought);

      const showActiveTools =
        isActivelyStreaming && activeToolCalls && activeToolCalls.size > 0;
      const hasHistoricalTools = msg.tool_calls && msg.tool_calls.length > 0;
      const hasContent = msg.content && msg.content.trim().length > 0;
      const useInterleavedRendering = timeline.length > 0;

      const renderTimelineItems = () => {
        const toolResultsMap = new Map(
          (msg.tool_results || []).map((r) => [r.tool_name, r])
        );

        return timeline.map((item, idx) => {
          const isLastItem = idx === timeline.length - 1;

          if (item.type === "thought") {
            return renderSingleThought(
              item.content || "",
              idx,
              isThinking && isLastItem,
              isLastItem
            );
          }

          if (item.type === "tool_call" && item.toolName) {
            const result = toolResultsMap.get(item.toolName);
            const execution = toolExecutions?.[item.toolName];
            const status = result
              ? result.error
                ? "error"
                : "success"
              : "success";

            return (
              <AgentSection
                key={`timeline-tool-${item.id}`}
                icon="construction"
                iconBg="bg-slate-200 dark:bg-border-dark"
                opacity={!isActivelyStreaming}
              >
                <ToolExecutionCardDisplay
                  toolName={item.toolName}
                  status={status}
                  parameters={item.toolInput}
                  duration={execution?.duration}
                  result={result?.result}
                  error={result?.error}
                  defaultExpanded={false}
                />
              </AgentSection>
            );
          }

          return null;
        });
      };

      const displayThoughts =
        isActivelyStreaming && currentThought
          ? [...thoughts.filter((t) => t !== currentThought), currentThought]
          : thoughts;
      const hasThoughts = displayThoughts.length > 0 || isThinking;

      return (
        <div className="space-y-4 animate-slide-up pb-8 pt-4">
          {useInterleavedRendering &&
            !isActivelyStreaming &&
            renderTimelineItems()}

          {isActivelyStreaming && (
            <>
              {useInterleavedRendering && renderTimelineItems()}

              {isThinking &&
                currentThought &&
                !timeline.some(
                  (t) => t.type === "thought" && t.content === currentThought
                ) &&
                renderSingleThought(
                  currentThought,
                  timeline.length,
                  true,
                  true
                )}

              {showActiveTools && renderActiveTools()}
            </>
          )}

          {!useInterleavedRendering && !isActivelyStreaming && (
            <>
              {hasThoughts && renderThoughts(displayThoughts, isThinking)}

              {hasHistoricalTools &&
                renderHistoricalTools(
                  msg.tool_calls,
                  msg.tool_results,
                  toolExecutions
                )}
            </>
          )}

          {hasContent && (
            <AssistantMessage
              content={msg.content}
              isReport={msg.metadata?.isReport === true}
              generatedAt={msg.created_at}
            />
          )}

          {isActivelyStreaming &&
            !hasContent &&
            !hasThoughts &&
            !showActiveTools &&
            !hasHistoricalTools &&
            timeline.length === 0 && (
              <AgentSection icon="psychology">
                <div className="bg-slate-50 dark:bg-surface-dark/50 border border-slate-200 dark:border-border-dark rounded-2xl rounded-tl-none p-4">
                  <div className="flex items-center gap-2 text-slate-500">
                    <span className="material-symbols-outlined text-sm spinner">
                      autorenew
                    </span>
                    <span className="text-sm">Processing...</span>
                  </div>
                </div>
              </AgentSection>
            )}
        </div>
      );
    }

    // System or other message types
    return (
      <div className="text-center text-xs text-slate-400 py-2">
        {msg.content}
      </div>
    );
  }, [messages, isStreaming, currentThought, activeToolCalls, agentState, renderSingleThought, renderThoughts, renderHistoricalTools, renderActiveTools]);

  // Empty state
  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        <MessageStream className="max-w-4xl mx-auto">
          <div className="flex items-center justify-center h-96">
            <div className="text-center text-slate-500 dark:text-slate-400">
              <span className="material-symbols-outlined text-4xl mb-2">chat</span>
              <p>No messages yet. Start a conversation!</p>
            </div>
          </div>
        </MessageStream>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
      <MessageStream className="max-w-4xl mx-auto">
        <div
          ref={scrollContainerRef}
          data-testid="virtual-scroll-container"
          className="overflow-auto"
          style={{ height: `${containerHeight}px` }}
        >
          <div
            data-testid="virtual-message-list"
            style={{
              position: "relative",
              height: `${totalSize}px`,
              width: "100%",
            }}
          >
            {virtualRows.map((virtualRow) => {
              const msg = messages[virtualRow.index];
              if (!msg) return null;

              return (
                <div
                  key={virtualRow.key}
                  data-testid={`virtual-row-${virtualRow.index}`}
                  ref={rowVirtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  {renderMessage(msg, virtualRow.index)}
                </div>
              );
            })}
          </div>
        </div>
        <div ref={bottomRef} />
      </MessageStream>
    </div>
  );
};
