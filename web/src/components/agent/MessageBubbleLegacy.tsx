/**
 * MessageBubble component
 *
 * Displays a single message in the chat interface with appropriate
 * styling based on the message role (user/assistant) and type.
 *
 * Extended for multi-level thinking with work_plan, step_start, step_end message types.
 * Extended for structured output with ReportViewer and TableView (T125).
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 * Only re-renders when message content, role, status, or type changes.
 */

import React, { memo } from "react";
import { Card, Avatar, Typography, Tag, Space, Collapse, Image } from "antd";
import {
  UserOutlined,
  RobotOutlined,
  BulbOutlined,
  ToolOutlined,
  ThunderboltOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import type {
  ArtifactReference,
  Message,
  MessageRole,
  MessageType,
} from "../../types/agent";
import { WorkPlanCard } from "./WorkPlanCard";
import { ThoughtBubble } from "./ThoughtBubble";
import { ToolExecutionCard } from "./ToolExecutionCard";
import type { WorkPlan } from "../../types/agent";
import { ReportViewer } from "./ReportViewer";
import { TableView } from "./TableView";

const { Text, Paragraph } = Typography;

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

interface StructuredOutputData {
  format: "markdown" | "table" | "code" | "json" | "yaml";
  content: string;
  title?: string;
}

const roleColors: Record<MessageRole, string> = {
  user: "#1890ff",
  assistant: "#52c41a",
  system: "#8c8c8c",
};

const roleIcons: Record<MessageRole, React.ReactNode> = {
  user: <UserOutlined />,
  assistant: <RobotOutlined />,
  system: <BulbOutlined />,
};

const typeColors: Record<MessageType, string> = {
  text: "default",
  thought: "processing",
  tool_call: "warning",
  tool_result: "success",
  error: "error",
  work_plan: "blue",
  step_start: "cyan",
  step_end: "purple",
};

const typeLabels: Record<MessageType, string> = {
  text: "",
  thought: "Thinking",
  tool_call: "Tool Call",
  tool_result: "Tool Result",
  error: "Error",
  work_plan: "Work Plan",
  step_start: "Step Start",
  step_end: "Step End",
};

const typeIcons: Record<MessageType, React.ReactNode> = {
  text: null,
  thought: <BulbOutlined />,
  tool_call: <ToolOutlined />,
  tool_result: <CheckCircleOutlined />,
  error: <BulbOutlined />,
  work_plan: <ThunderboltOutlined />,
  step_start: <PlayCircleOutlined />,
  step_end: <CheckCircleOutlined />,
};

const MessageBubbleInternal: React.FC<MessageBubbleProps> = ({
  message,
  isStreaming = false,
}) => {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const hasTypeLabel = message.message_type !== "text";

  // Parse work_plan from metadata for new message types
  const workPlan =
    message.message_type === "work_plan" && message.metadata?.workPlan
      ? (message.metadata.workPlan as WorkPlan)
      : null;

  // Parse step info from metadata for step_start/step_end messages
  const stepInfo =
    message.message_type === "step_start" || message.message_type === "step_end"
      ? (message.metadata?.stepInfo as {
          step_number?: number;
          total_steps?: number;
        } | null)
      : null;

  // T125: Parse structured output from metadata
  const structuredOutput = message.metadata?.structuredOutput as
    | StructuredOutputData
    | undefined;

  // T125: Parse table data from metadata
  const tableData = message.metadata?.tableData as
    | Record<string, any>[]
    | undefined;

  // Parse stored execution details from metadata for assistant messages
  // This allows displaying execution process after completion
  const hasStoredExecutionDetails =
    message.role === "assistant" &&
    message.metadata &&
    (!!message.metadata.work_plan ||
      !!message.metadata.thoughts ||
      !!message.metadata.execution_events ||
      (message.tool_calls && message.tool_calls.length > 0) ||
      (message.tool_results && message.tool_results.length > 0));

  // Debug: log execution details check
  if (message.role === "assistant") {
    console.log("[MessageBubble] Assistant message execution check:", {
      id: message.id,
      has_metadata: !!message.metadata,
      metadata_keys: message.metadata ? Object.keys(message.metadata) : [],
      has_work_plan: !!message.metadata?.work_plan,
      has_thoughts: !!message.metadata?.thoughts,
      has_execution_events: !!message.metadata?.execution_events,
      tool_calls_count: message.tool_calls?.length || 0,
      tool_results_count: message.tool_results?.length || 0,
      hasStoredExecutionDetails,
    });
  }

  const storedWorkPlan = message.metadata?.work_plan as WorkPlan | undefined;
  const storedThoughts = message.metadata?.thoughts as
    | Array<{
        thought: string;
        thought_level: string;
        timestamp: string;
      }>
    | undefined;

  // Build tool call list from stored metadata for display
  const executionEvents = message.metadata?.execution_events as
    | Array<{
        type: string;
        data?: {
          tool_name?: string;
          tool_input?: Record<string, unknown>;
          step_number?: number;
        };
      }>
    | undefined;
  const storedToolCalls =
    executionEvents
      ?.filter((e) => e.type === "act")
      .map((e) => ({
        name: e.data?.tool_name,
        input: e.data?.tool_input,
        stepNumber: e.data?.step_number,
      })) ?? [];

  const artifacts =
    (message.artifacts as ArtifactReference[] | undefined) ||
    (message.metadata?.artifacts as ArtifactReference[] | undefined);

  const renderArtifactLink = (artifact: ArtifactReference) => {
    const nameFromKey = artifact.object_key?.split("/")?.pop();
    const nameFromUrl = artifact.url?.split("/")?.pop()?.split("?")?.[0];
    const displayName = nameFromKey || nameFromUrl || "artifact";
    return (
      <a href={artifact.url} target="_blank" rel="noreferrer">
        <Space size={6}>
          <LinkOutlined />
          <Text>{displayName}</Text>
          {artifact.size_bytes ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              ({(artifact.size_bytes / 1024).toFixed(1)} KB)
            </Text>
          ) : null}
        </Space>
      </a>
    );
  };

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        marginBottom: 16,
      }}
    >
      <Card
        size="small"
        style={{
          maxWidth: "85%",
          backgroundColor: isUser
            ? "#e6f7ff"
            : isSystem
            ? "#f5f5f5"
            : "#f6ffed",
          border: `1px solid ${roleColors[message.role]}40`,
        }}
      >
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          {/* Header with role icon and type label */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Avatar
              size={24}
              icon={roleIcons[message.role]}
              style={{ backgroundColor: roleColors[message.role] }}
            />
            {hasTypeLabel && (
              <Tag
                color={typeColors[message.message_type]}
                icon={typeIcons[message.message_type]}
              >
                {typeLabels[message.message_type]}
              </Tag>
            )}
            {message.message_type === "tool_call" &&
              message.tool_calls?.map((call, idx) => (
                <Tag key={idx} icon={<ToolOutlined />} color="warning">
                  {call.name}
                </Tag>
              ))}
            {/* T125: Structured output indicator */}
            {structuredOutput && (
              <Tag icon={<FileTextOutlined />} color="blue">
                Structured Output
              </Tag>
            )}
            {/* T125: Table data indicator */}
            {tableData && (
              <Tag icon={<FileTextOutlined />} color="green">
                Table Data
              </Tag>
            )}
            {/* Step info for step_start/step_end */}
            {stepInfo && (
              <Tag color="default">
                Step{" "}
                {typeof stepInfo.step_number === "number"
                  ? stepInfo.step_number + 1
                  : "?"}{" "}
                /{" "}
                {typeof stepInfo.total_steps === "number"
                  ? stepInfo.total_steps
                  : "?"}
              </Tag>
            )}
            {/* Indicator for stored execution details */}
            {hasStoredExecutionDetails && (
              <Tag icon={<CheckCircleOutlined />} color="success">
                Execution Complete
              </Tag>
            )}
          </div>

          {/* Message content */}
          {/* Work Plan - render WorkPlanCard component */}
          {message.message_type === "work_plan" && workPlan ? (
            <WorkPlanCard workPlan={workPlan} />
          ) : message.message_type === "thought" ? (
            <Text type="secondary" italic>
              {message.content}
            </Text>
          ) : message.message_type === "tool_call" &&
            message.tool_calls?.length ? (
            <div>
              {message.tool_calls.map((call, idx) => (
                <div key={idx} style={{ marginTop: 8 }}>
                  <Text strong>{call.name}</Text>
                  <pre
                    style={{
                      background: "#f5f5f5",
                      padding: 8,
                      borderRadius: 4,
                      fontSize: 12,
                      marginTop: 4,
                      overflow: "auto",
                      maxHeight: 200,
                    }}
                  >
                    {JSON.stringify(call.arguments, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          ) : message.message_type === "tool_result" &&
            message.tool_results?.length ? (
            <div>
              {message.tool_results.map((result, idx) => (
                <div key={idx} style={{ marginTop: 8 }}>
                  <Text strong>{result.tool_name}</Text>
                  <pre
                    style={{
                      background: "#f5f5f5",
                      padding: 8,
                      borderRadius: 4,
                      fontSize: 12,
                      marginTop: 4,
                      overflow: "auto",
                      maxHeight: 200,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {result.result || result.error || "No result"}
                  </pre>
                </div>
              ))}
            </div>
          ) : (
            <>
              {/* T125: Render structured output if present */}
              {structuredOutput ? (
                <ReportViewer
                  content={structuredOutput.content}
                  format={structuredOutput.format}
                  title={structuredOutput.title || "Structured Output"}
                  filename={structuredOutput.title || "output"}
                  showDownload={true}
                />
              ) : tableData ? (
                <TableView
                  data={tableData}
                  title="Table Data"
                  filename="table"
                  showSearch={true}
                  showExport={true}
                  size="small"
                  pagination={{ pageSize: 5 }}
                />
              ) : (
                <Paragraph
                  style={{
                    margin: 0,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {message.content}
                  {isStreaming && (
                    <span
                      style={{
                        display: "inline-block",
                        width: 2,
                        height: "1em",
                        backgroundColor: "#52c41a",
                        marginLeft: 2,
                        verticalAlign: "text-bottom",
                        animation: "typing-cursor-blink 1s step-end infinite",
                      }}
                    />
                  )}
                </Paragraph>
              )}
            </>
          )}

          {artifacts && artifacts.length > 0 && (
            <Collapse
              defaultActiveKey={[]}
              ghost
              items={[
                {
                  key: "artifacts",
                  label: (
                    <Text strong style={{ fontSize: 12 }}>
                      <FileTextOutlined /> Artifacts
                    </Text>
                  ),
                  children: (
                    <Space direction="vertical" size="small">
                      {artifacts.map((artifact, idx) => {
                        const isImage =
                          artifact.mime_type?.startsWith("image/") ?? false;
                        return (
                          <div key={idx}>
                            {isImage ? (
                              <Image
                                src={artifact.url}
                                alt={artifact.object_key || `artifact-${idx + 1}`}
                                width={220}
                                style={{ borderRadius: 6 }}
                              />
                            ) : (
                              renderArtifactLink(artifact)
                            )}
                          </div>
                        );
                      })}
                    </Space>
                  ),
                },
              ]}
            />
          )}

          {/* Stored execution details - shown with reduced opacity for completed executions */}
          {hasStoredExecutionDetails && (
            <div
              style={{
                opacity: 0.7,
                marginTop: 12,
                borderTop: "1px solid #d9d9d9",
                paddingTop: 8,
              }}
            >
              <Collapse
                defaultActiveKey={[]}
                ghost
                items={[
                  {
                    key: "execution-details",
                    label: (
                      <Text strong style={{ fontSize: 12 }}>
                        <FileTextOutlined /> Execution Details
                      </Text>
                    ),
                    children: (
                      <Space
                        direction="vertical"
                        size="small"
                        style={{ width: "100%" }}
                      >
                        {/* Stored Work Plan */}
                        {storedWorkPlan && (
                          <div>
                            <Text strong style={{ fontSize: 12 }}>
                              Work Plan:
                            </Text>
                            <WorkPlanCard workPlan={storedWorkPlan} />
                          </div>
                        )}

                        {/* Stored Thoughts */}
                        {storedThoughts && storedThoughts.length > 0 && (
                          <div>
                            <Text strong style={{ fontSize: 12 }}>
                              Thoughts:
                            </Text>
                            {storedThoughts.map((thoughtData, idx) => (
                              <ThoughtBubble
                                key={idx}
                                thought={thoughtData.thought}
                                level={
                                  thoughtData.thought_level as "work" | "task"
                                }
                                isThinking={false}
                              />
                            ))}
                          </div>
                        )}

                        {/* Stored Tool Calls */}
                        {storedToolCalls.length > 0 && (
                          <div>
                            <Text strong style={{ fontSize: 12 }}>
                              Tool Executions:
                            </Text>
                            {storedToolCalls.map(
                              (
                                tc: {
                                  name?: string;
                                  input?: Record<string, unknown>;
                                  stepNumber?: number;
                                },
                                idx: number
                              ) => (
                                <ToolExecutionCard
                                  key={idx}
                                  toolCall={{
                                    name: tc.name || "unknown",
                                    input: tc.input || {},
                                    stepNumber: tc.stepNumber,
                                  }}
                                />
                              )
                            )}
                          </div>
                        )}

                        {/* Stored Tool Results */}
                        {message.tool_results &&
                          message.tool_results.length > 0 && (
                            <div>
                              <Text strong style={{ fontSize: 12 }}>
                                Tool Results:
                              </Text>
                              {message.tool_results.map((result, idx) => (
                                <div
                                  key={idx}
                                  style={{
                                    marginTop: 4,
                                    padding: 8,
                                    background: "#f5f5f5",
                                    borderRadius: 4,
                                    fontSize: 12,
                                  }}
                                >
                                  <Text strong>
                                    {result.tool_name || `Tool ${idx + 1}`}
                                  </Text>
                                  <pre
                                    style={{
                                      marginTop: 4,
                                      whiteSpace: "pre-wrap",
                                      wordBreak: "break-word",
                                      maxHeight: 150,
                                      overflow: "auto",
                                    }}
                                  >
                                    {result.error ? (
                                      <Text type="danger">
                                        {result.error || result.result}
                                      </Text>
                                    ) : (
                                      result.result
                                    )}
                                  </pre>
                                </div>
                              ))}
                            </div>
                          )}
                      </Space>
                    ),
                  },
                ]}
              />
            </div>
          )}

          {/* Langfuse Trace Link */}
          {message.traceUrl && (
            <div
              style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: "1px dashed #d9d9d9",
                fontSize: 12,
              }}
            >
              <a
                href={message.traceUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "#8c8c8c" }}
              >
                <LinkOutlined style={{ marginRight: 4 }} />
                View Trace
              </a>
            </div>
          )}
        </Space>
      </Card>
    </div>
  );
};

/**
 * Memoized MessageBubble component with custom comparison.
 * Only re-renders when critical message properties change.
 */
export const MessageBubble = memo(
  MessageBubbleInternal,
  (prevProps, nextProps) => {
    const prevMsg = prevProps.message;
    const nextMsg = nextProps.message;

    // Quick ID check
    if (prevMsg.id !== nextMsg.id) return false;

    // Check critical properties that affect rendering
    return (
      prevMsg.content === nextMsg.content &&
      prevMsg.role === nextMsg.role &&
      prevMsg.message_type === nextMsg.message_type &&
      prevMsg.traceUrl === nextMsg.traceUrl &&
      JSON.stringify(prevMsg.metadata) === JSON.stringify(nextMsg.metadata) &&
      JSON.stringify(prevMsg.tool_calls) ===
        JSON.stringify(nextMsg.tool_calls) &&
      JSON.stringify(prevMsg.tool_results) ===
        JSON.stringify(nextMsg.tool_results)
    );
  }
);

MessageBubble.displayName = "MessageBubble";
MessageBubble.displayName = "MessageBubble";
