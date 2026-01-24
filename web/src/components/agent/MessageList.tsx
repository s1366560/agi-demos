/**
 * MessageList component
 *
 * Displays a scrollable list of messages in the conversation.
 *
 * Extended for multi-level thinking observability with WorkPlanCard,
 * ThoughtBubble, ToolExecutionCard, and AgentProgressBar components.
 */

import React, { useEffect, useRef } from "react";
import { Spin, Empty } from "antd";
import { MessageBubble } from "./MessageBubble";
import { WorkPlanCard } from "./WorkPlanCard";
import { ThoughtBubble } from "./ThoughtBubble";
import { ToolExecutionCard } from "./ToolExecutionCard";
import { SkillExecutionCard } from "./SkillExecutionCard";
import { AgentProgressBar } from "./AgentProgressBar";
import { useAgentStore, useCurrentSkillExecution } from "../../stores/agent";
import type { Message } from "../../types/agent";

interface MessageListProps {
  messages: Message[];
  loading?: boolean;
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  loading = false,
}) => {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const {
    currentWorkPlan,
    currentStepNumber,
    currentStepStatus,
    currentThought,
    currentThoughtLevel,
    currentToolCall,
    currentObservation,
    isStreaming,
    assistantDraftContent,
    isTextStreaming,
  } = useAgentStore();

  // Skill execution state (L2 layer)
  const currentSkillExecution = useCurrentSkillExecution();

  // Auto-scroll to bottom when new messages arrive or streaming state changes
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [
    messages,
    currentObservation,
    currentToolCall,
    currentWorkPlan,
    currentThought,
    currentStepNumber,
    assistantDraftContent,
    currentSkillExecution,
  ]);

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (messages.length === 0 && !isStreaming) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
        <Empty description="Start a conversation by typing a message below" />
      </div>
    );
  }

  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        padding: "16px 24px",
        backgroundColor: "#fafafa",
      }}
    >
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {/* Real-time observability components during streaming */}
      {isStreaming && (
        <>
          {/* Work Plan Display */}
          {currentWorkPlan && <WorkPlanCard workPlan={currentWorkPlan} />}

          {/* Progress Bar */}
          {currentWorkPlan && currentStepNumber !== null && (
            <AgentProgressBar
              current={currentStepNumber + 1}
              total={currentWorkPlan.steps.length}
              status={
                currentStepStatus === "running"
                  ? "step_executing"
                  : currentStepStatus === "completed"
                  ? "observing"
                  : currentStepStatus === "failed"
                  ? "failed"
                  : "thinking"
              }
              showSteps={true}
              compact={false}
              animate={true}
            />
          )}

          {/* Skill Execution Card (L2 layer) */}
          {currentSkillExecution && (
            <SkillExecutionCard skillExecution={currentSkillExecution} />
          )}

          {/* Thought Bubble */}
          {currentThought && currentThoughtLevel && (
            <ThoughtBubble
              thought={currentThought}
              level={currentThoughtLevel}
              stepNumber={currentStepNumber ?? undefined}
              isThinking={true}
            />
          )}

          {/* Tool Execution Card */}
          {currentToolCall && (
            <ToolExecutionCard
              toolCall={{
                name: currentToolCall.name,
                input: currentToolCall.input,
                stepNumber: currentToolCall.stepNumber,
              }}
            />
          )}

          {/* Observation */}
          {currentObservation && (
            <div
              style={{
                display: "flex",
                justifyContent: "flex-start",
                marginBottom: 16,
              }}
            >
              <div
                style={{
                  background: "#f6ffed",
                  border: "1px solid #b7eb8f",
                  borderRadius: 8,
                  padding: "8px 16px",
                  maxWidth: "70%",
                }}
              >
                <div style={{ fontSize: 12 }}>
                  <div style={{ fontWeight: "bold", marginBottom: 4 }}>
                    Observation:
                  </div>
                  <div
                    style={{
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      maxHeight: 200,
                      overflow: "auto",
                    }}
                  >
                    {currentObservation}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Typewriter effect message during text streaming */}
          {isTextStreaming && assistantDraftContent && (
            <MessageBubble
              message={{
                id: "streaming-draft",
                conversation_id: "",
                role: "assistant",
                content: assistantDraftContent,
                message_type: "text",
                created_at: new Date().toISOString(),
              }}
              isStreaming={true}
            />
          )}

          {/* Generic streaming indicator when no specific state */}
          {!currentWorkPlan &&
            !currentThought &&
            !currentToolCall &&
            !isTextStreaming && (
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-start",
                  marginBottom: 16,
                }}
              >
                <div
                  style={{
                    background: "#f6ffed",
                    border: "1px solid #b7eb8f",
                    borderRadius: 8,
                    padding: "8px 16px",
                  }}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <Spin size="small" />
                    <span style={{ color: "#52c41a", fontSize: 12 }}>
                      Agent is thinking...
                    </span>
                  </div>
                </div>
              </div>
            )}
        </>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
};
