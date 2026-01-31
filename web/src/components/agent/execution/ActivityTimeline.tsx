/**
 * ActivityTimeline - Atomic-level activity timeline for agent execution
 *
 * Displays the agent's execution process as a vertical timeline showing
 * individual thoughts and tool calls in chronological order.
 *
 * Unlike ExecutionTimeline which focuses on Work Plan steps, this component
 * shows atomic-level activities (Thought → Tool → Result) for detailed debugging.
 */

import React, { useMemo, useRef, useEffect, memo } from "react";
import { Collapse, Tooltip } from "antd";
import {
  BulbOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  SyncOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from "@ant-design/icons";
import type { ToolCall, ToolResult } from "../../../types/agent";

/**
 * Timeline item representing a single activity
 */
export interface TimelineItem {
  type: "thought" | "tool_call";
  id: string;
  content?: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  timestamp: number;
}

/**
 * Tool execution timing information
 */
export interface ToolExecutionInfo {
  startTime?: number;
  endTime?: number;
  duration?: number;
}

export interface ActivityTimelineProps {
  /** Timeline items (from agent store) */
  timeline: TimelineItem[];
  /** Tool execution details with timing */
  toolExecutions?: Record<string, ToolExecutionInfo>;
  /** Tool call list */
  toolCalls?: ToolCall[];
  /** Tool result list */
  toolResults?: ToolResult[];
  /** Whether execution is in progress */
  isActive?: boolean;
  /** Compact mode for sidebar display */
  compact?: boolean;
  /** Maximum items to show before "show more" */
  maxItems?: number;
  /** Auto-scroll to latest activity */
  autoScroll?: boolean;
}

// Helper to format relative time
const formatRelativeTime = (timestamp: number): string => {
  const diff = Date.now() - timestamp;
  if (diff < 1000) return "now";
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
};

// Format duration in ms to human readable
const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

// Sequence number formatter (circled numbers)
const formatSequenceNumber = (num: number): string => {
  const circledNumbers = [
    "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
    "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳",
  ];
  return num <= 20 ? circledNumbers[num - 1] : `${num}.`;
};

/**
 * Individual activity node in the timeline
 */
interface ActivityNodeProps {
  type: "thought" | "tool_call";
  sequence: number;
  timestamp: number;
  children: React.ReactNode;
  isLast: boolean;
  status?: "running" | "success" | "failed";
  duration?: number;
  compact?: boolean;
}

const ActivityNode: React.FC<ActivityNodeProps> = ({
  type,
  sequence,
  timestamp,
  children,
  isLast,
  status,
  duration,
  compact = false,
}) => {
  const isThought = type === "thought";
  const isRunning = status === "running";

  const getStatusIcon = () => {
    if (isThought) {
      return (
        <BulbOutlined
          className={`text-amber-500 ${isRunning ? "animate-pulse" : ""}`}
        />
      );
    }
    switch (status) {
      case "running":
        return <SyncOutlined spin className="text-blue-500" />;
      case "success":
        return <CheckCircleOutlined className="text-emerald-500" />;
      case "failed":
        return <CloseCircleOutlined className="text-red-500" />;
      default:
        return <ToolOutlined className="text-blue-500" />;
    }
  };

  return (
    <div className={`relative ${compact ? "pl-6 pb-2" : "pl-8 pb-4"}`}>
      {/* Connecting line */}
      {!isLast && (
        <div
          className={`absolute ${
            compact ? "left-[5px]" : "left-[7px]"
          } top-5 bottom-0 w-0.5 border-l-2 border-dashed ${
            isThought
              ? "border-amber-200 dark:border-amber-800"
              : "border-blue-200 dark:border-blue-800"
          }`}
        />
      )}

      {/* Status dot */}
      <div
        className={`absolute left-0 top-1 ${
          compact ? "w-3 h-3" : "w-4 h-4"
        } rounded-full border-2 flex items-center justify-center transition-all ${
          isThought
            ? "bg-amber-100 dark:bg-amber-900/30 border-amber-400 dark:border-amber-600"
            : status === "running"
            ? "bg-blue-100 dark:bg-blue-900/30 border-blue-400 dark:border-blue-600 animate-pulse"
            : status === "success"
            ? "bg-emerald-100 dark:bg-emerald-900/30 border-emerald-400 dark:border-emerald-600"
            : status === "failed"
            ? "bg-red-100 dark:bg-red-900/30 border-red-400 dark:border-red-600"
            : "bg-blue-100 dark:bg-blue-900/30 border-blue-400 dark:border-blue-600"
        }`}
      >
        <div
          className={`${compact ? "w-1" : "w-1.5"} h-${
            compact ? "1" : "1.5"
          } rounded-full ${
            isThought
              ? "bg-amber-500"
              : status === "success"
              ? "bg-emerald-500"
              : status === "failed"
              ? "bg-red-500"
              : "bg-blue-500"
          }`}
        />
      </div>

      {/* Activity content */}
      <div
        className={`rounded-lg ${compact ? "p-2" : "p-3"} ${
          isThought
            ? "bg-amber-50/50 dark:bg-amber-900/10 border border-amber-100 dark:border-amber-800/50"
            : status === "failed"
            ? "bg-red-50/50 dark:bg-red-900/10 border border-red-100 dark:border-red-800/50"
            : "bg-blue-50/30 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-800/50"
        }`}
      >
        {/* Header with icon, sequence, timestamp, and duration */}
        <div className="flex items-center gap-2 mb-1">
          {getStatusIcon()}
          <span
            className={`${
              compact ? "text-[10px]" : "text-xs"
            } font-semibold text-slate-600 dark:text-slate-400`}
          >
            {formatSequenceNumber(sequence)} {isThought ? "Thought" : "Tool"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            {duration !== undefined && (
              <Tooltip title="Execution time">
                <span className="flex items-center gap-1 text-[10px] text-slate-400 dark:text-slate-500">
                  <ClockCircleOutlined className="text-[10px]" />
                  {formatDuration(duration)}
                </span>
              </Tooltip>
            )}
            <span
              className={`${
                compact ? "text-[10px]" : "text-xs"
              } text-slate-400 dark:text-slate-500`}
            >
              {formatRelativeTime(timestamp)}
            </span>
          </div>
        </div>

        {/* Content */}
        <div
          className={
            isThought
              ? `text-slate-600 dark:text-slate-300 ${
                  compact ? "text-xs" : "text-sm"
                } italic`
              : ""
          }
        >
          {children}
        </div>
      </div>
    </div>
  );
};

/**
 * Tool card component for displaying tool execution details
 */
interface ToolCardInlineProps {
  toolName: string;
  input?: Record<string, unknown>;
  result?: string;
  error?: string;
  status: "running" | "success" | "failed";
  compact?: boolean;
}

const ToolCardInline: React.FC<ToolCardInlineProps> = ({
  toolName,
  input,
  result,
  error,
  status,
  compact = false,
}) => {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <span
          className={`font-medium ${
            compact ? "text-xs" : "text-sm"
          } text-slate-700 dark:text-slate-200`}
        >
          {toolName}
        </span>
        <span
          className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
            status === "success"
              ? "bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400"
              : status === "failed"
              ? "bg-red-100 dark:bg-red-900/50 text-red-600 dark:text-red-400"
              : "bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400"
          }`}
        >
          {status.toUpperCase()}
        </span>
      </div>

      {input && Object.keys(input).length > 0 && (
        <Collapse
          ghost
          size="small"
          className="bg-transparent"
          items={[
            {
              key: "details",
              label: (
                <span className="text-[10px] text-slate-500 dark:text-slate-400">
                  View details
                </span>
              ),
              children: (
                <div className="space-y-2">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-slate-400 dark:text-slate-500">
                      Input
                    </span>
                    <pre
                      className={`${
                        compact ? "p-1.5 text-[10px]" : "p-2 text-xs"
                      } rounded bg-white/80 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 overflow-x-auto max-w-full whitespace-pre-wrap break-all max-h-32`}
                    >
                      {JSON.stringify(input, null, 2)}
                    </pre>
                  </div>
                  {result && (
                    <div>
                      <span className="text-[10px] uppercase font-bold text-slate-400 dark:text-slate-500">
                        Result
                      </span>
                      <pre
                        className={`${
                          compact ? "p-1.5 text-[10px]" : "p-2 text-xs"
                        } rounded bg-white/80 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 overflow-x-auto max-w-full whitespace-pre-wrap break-all max-h-32`}
                      >
                        {result}
                      </pre>
                    </div>
                  )}
                  {error && (
                    <div>
                      <span className="text-[10px] uppercase font-bold text-red-400">
                        Error
                      </span>
                      <pre className="p-1.5 text-[10px] rounded bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 overflow-x-auto max-w-full whitespace-pre-wrap break-all">
                        {error}
                      </pre>
                    </div>
                  )}
                </div>
              ),
            },
          ]}
        />
      )}
    </div>
  );
};

/**
 * ActivityTimeline component
 * Memoized to prevent unnecessary re-renders (rerender-memo)
 */
const ActivityTimelineInternal: React.FC<ActivityTimelineProps> = ({
  timeline,
  toolExecutions = {},
  toolResults = [],
  isActive = false,
  compact = false,
  maxItems = 10,
  autoScroll = true,
}) => {
  const [showAll, setShowAll] = React.useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Merge tool results with timeline items
  const enrichedTimeline = useMemo(() => {
    return timeline.map((item) => {
      if (item.type === "tool_call" && item.toolName) {
        const result = toolResults.find((r) => r.tool_name === item.toolName);
        const execution = toolExecutions[item.toolName];
        return {
          ...item,
          result: result?.result as string | undefined,
          error: result?.error as string | undefined,
          status: (result
            ? result.error
              ? "failed"
              : "success"
            : "running") as "running" | "success" | "failed",
          duration: execution?.duration as number | undefined,
        };
      }
      return {
        ...item,
        result: undefined as string | undefined,
        error: undefined as string | undefined,
        status: undefined as "running" | "success" | "failed" | undefined,
        duration: undefined as number | undefined,
      };
    });
  }, [timeline, toolResults, toolExecutions]);

  // Display items based on showAll state
  const displayItems = useMemo(() => {
    if (showAll || enrichedTimeline.length <= maxItems) {
      return enrichedTimeline;
    }
    return enrichedTimeline.slice(-maxItems);
  }, [enrichedTimeline, showAll, maxItems]);

  // Auto-scroll to bottom when new items arrive
  useEffect(() => {
    if (autoScroll && containerRef.current && isActive) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [enrichedTimeline.length, autoScroll, isActive]);

  if (timeline.length === 0 && !isActive) {
    return null;
  }

  const header = (
    <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
      <BulbOutlined
        className={isActive ? "animate-pulse text-amber-500" : ""}
      />
      <span className={`${compact ? "text-[10px]" : "text-xs"} font-medium`}>
        {isActive ? "Processing..." : "Activity Timeline"}
      </span>
      {timeline.length > 0 && (
        <span
          className={`ml-auto ${
            compact ? "text-[10px]" : "text-xs"
          } text-slate-400`}
        >
          {timeline.length} activities
        </span>
      )}
    </div>
  );

  return (
    <Collapse
      ghost
      size="small"
      defaultActiveKey={isActive ? ["1"] : []}
      className={`${
        compact ? "mb-2" : "mb-4"
      } bg-slate-50/50 dark:bg-slate-800/30 rounded-lg border border-slate-100 dark:border-slate-700 w-full max-w-full`}
      items={[
        {
          key: "1",
          label: header,
          children: (
            <div
              ref={containerRef}
              className={`${
                compact ? "py-1 max-h-60" : "py-2 max-h-96"
              } overflow-y-auto max-w-full`}
            >
              {/* Show more button */}
              {!showAll && enrichedTimeline.length > maxItems && (
                <div className="text-center mb-2">
                  <button
                    onClick={() => setShowAll(true)}
                    className="text-xs text-primary hover:underline"
                  >
                    Show {enrichedTimeline.length - maxItems} earlier activities
                  </button>
                </div>
              )}

              {/* Timeline items */}
              {displayItems.map((item, index) => {
                const isLast = index === displayItems.length - 1;
                const sequence = showAll
                  ? index + 1
                  : enrichedTimeline.length - maxItems + index + 1;

                if (item.type === "thought") {
                  return (
                    <ActivityNode
                      key={item.id}
                      type="thought"
                      sequence={sequence > 0 ? sequence : index + 1}
                      timestamp={item.timestamp}
                      isLast={isLast && !isActive}
                      compact={compact}
                    >
                      <span className="break-words">{item.content}</span>
                    </ActivityNode>
                  );
                } else {
                  return (
                    <ActivityNode
                      key={item.id}
                      type="tool_call"
                      sequence={sequence > 0 ? sequence : index + 1}
                      timestamp={item.timestamp}
                      isLast={isLast && !isActive}
                      status={item.status}
                      duration={item.duration}
                      compact={compact}
                    >
                      <ToolCardInline
                        toolName={item.toolName!}
                        input={item.toolInput}
                        result={item.result}
                        error={item.error}
                        status={item.status || "running"}
                        compact={compact}
                      />
                    </ActivityNode>
                  );
                }
              })}

              {/* Active indicator */}
              {isActive && (
                <div className={`relative ${compact ? "pl-6" : "pl-8"}`}>
                  <div
                    className={`absolute left-0 top-1 ${
                      compact ? "w-3 h-3" : "w-4 h-4"
                    } rounded-full bg-blue-100 dark:bg-blue-900/30 border-2 border-blue-400 dark:border-blue-600 animate-pulse flex items-center justify-center`}
                  >
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-ping" />
                  </div>
                  <div
                    className={`${
                      compact ? "text-[10px]" : "text-xs"
                    } text-slate-400 dark:text-slate-500 italic`}
                  >
                    Waiting for next activity...
                  </div>
                </div>
              )}
            </div>
          ),
          className: "max-w-full",
        },
      ]}
    />
  );
};

export const ActivityTimeline = memo(ActivityTimelineInternal);
ActivityTimeline.displayName = 'ActivityTimeline';

export default ActivityTimeline;
