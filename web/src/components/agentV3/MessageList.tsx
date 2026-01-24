import React, { useEffect, useRef, useMemo } from "react";
import { Message, ToolCall, ToolResult } from "../../types/agent";
import {
  MessageStream,
  UserMessage,
  AgentSection,
  ReasoningLogCard,
  ToolExecutionCardDisplay,
} from "../agent/chat/MessageStream";
import { AssistantMessage } from "../agent/chat/AssistantMessage";

interface MessageListProps {
  messages: Message[];
  isStreaming: boolean;
  currentThought?: string;
  /** Active tool calls from store (for realtime streaming) */
  activeToolCalls?: Map<
    string,
    ToolCall & { status: "running" | "success" | "failed"; startTime: number }
  >;
  /** Agent state for determining what to show */
  agentState?: "idle" | "thinking" | "acting" | "observing" | "awaiting_input";
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isStreaming,
  currentThought,
  activeToolCalls,
  agentState,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when content changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [
    messages.length,
    messages[messages.length - 1]?.content,
    currentThought,
    activeToolCalls?.size,
  ]);

  // Helper: Get tool result for a tool call
  const getToolResult = (toolName: string, toolResults?: ToolResult[]) => {
    return toolResults?.find((r) => r.tool_name === toolName);
  };

  // Helper: Render a single thought card
  const renderSingleThought = (
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
  };

  // Helper: Render thoughts section (legacy - all in one card)
  const renderThoughts = (thoughts: string[], isThinking: boolean) => {
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
  };

  // Helper: Render tool executions for historical messages
  const renderHistoricalTools = (
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
      const status = result ? (result.error ? "error" : "success") : "success"; // Default to success for historical without explicit result

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
  };

  // Helper: Render active tool calls (realtime streaming)
  const renderActiveTools = () => {
    if (!activeToolCalls || activeToolCalls.size === 0) return null;

    return Array.from(activeToolCalls.entries()).map(([toolName, tool]) => {
      // Map "failed" status to "error" for ToolExecutionCardDisplay
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
  };

  // Memoized message rendering
  const renderedMessages = useMemo(() => {
    return messages.map((msg, index) => {
      const isLastMessage = index === messages.length - 1;
      const isLastAssistant = msg.role === "assistant" && isLastMessage;

      // User message
      if (msg.role === "user") {
        return (
          <div key={msg.id} className="animate-fade-in-up">
            <UserMessage content={msg.content} />
          </div>
        );
      }

      // Assistant message - render execution flow + final response
      if (msg.role === "assistant") {
        // Get execution data from message metadata
        const thoughts = (msg.metadata?.thoughts as string[]) || [];
        // Timeline for interleaved display: [{type: "thought"|"tool_call", ...}]
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

        // For realtime streaming on last message
        const isActivelyStreaming = isLastAssistant && isStreaming;
        const isThinking =
          isActivelyStreaming &&
          (agentState === "thinking" || !!currentThought);

        // Determine if we should show historical tools or active tools
        const showActiveTools =
          isActivelyStreaming && activeToolCalls && activeToolCalls.size > 0;
        const hasHistoricalTools = msg.tool_calls && msg.tool_calls.length > 0;
        const hasContent = msg.content && msg.content.trim().length > 0;

        // Use timeline for interleaved rendering if available
        const useInterleavedRendering = timeline.length > 0;

        // Render interleaved timeline items (thought -> tool -> thought -> tool)
        const renderTimelineItems = () => {
          // Get tool results map for quick lookup
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

        // Fallback: combine stored thoughts with current thought for streaming (legacy mode)
        const displayThoughts =
          isActivelyStreaming && currentThought
            ? [...thoughts.filter((t) => t !== currentThought), currentThought]
            : thoughts;
        const hasThoughts = displayThoughts.length > 0 || isThinking;

        return (
          <div key={msg.id} className="space-y-4 animate-slide-up">
            {/* Interleaved Timeline Rendering (preferred) */}
            {useInterleavedRendering &&
              !isActivelyStreaming &&
              renderTimelineItems()}

            {/* Active streaming: show current thought and active tools */}
            {isActivelyStreaming && (
              <>
                {/* Render completed timeline items */}
                {useInterleavedRendering && renderTimelineItems()}

                {/* Current thinking indicator */}
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

                {/* Active tool calls */}
                {showActiveTools && renderActiveTools()}
              </>
            )}

            {/* Fallback: Legacy rendering when no timeline data */}
            {!useInterleavedRendering && !isActivelyStreaming && (
              <>
                {/* Thoughts Section (all in one card) */}
                {hasThoughts && renderThoughts(displayThoughts, isThinking)}

                {/* Tool Executions */}
                {hasHistoricalTools &&
                  renderHistoricalTools(
                    msg.tool_calls,
                    msg.tool_results,
                    toolExecutions
                  )}
              </>
            )}

            {/* Final Response */}
            {hasContent && (
              <AssistantMessage
                content={msg.content}
                isReport={msg.metadata?.isReport === true}
                generatedAt={msg.created_at}
              />
            )}

            {/* Streaming placeholder when no content yet */}
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

      // System or other message types - simple display
      return (
        <div key={msg.id} className="text-center text-xs text-slate-400 py-2">
          {msg.content}
        </div>
      );
    });
  }, [messages, isStreaming, currentThought, activeToolCalls, agentState]);

  return (
    <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
      <MessageStream className="max-w-4xl mx-auto">
        {renderedMessages}
        <div ref={bottomRef} />
      </MessageStream>
    </div>
  );
};
