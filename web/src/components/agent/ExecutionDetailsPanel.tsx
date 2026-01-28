/**
 * ExecutionDetailsPanel - Multi-view execution details panel
 *
 * Integrates new visualization components with backward-compatible ThinkingChain.
 * Provides tab switching between:
 * - thinking: Original ThinkingChain (default for backward compatibility)
 * - activity: Atomic-level ActivityTimeline
 * - tools: ToolCallVisualization with Grid/Timeline/Flow modes
 * - tokens: TokenUsageChart
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 * Only re-renders when message, isStreaming, or defaultView change.
 */

import React, { useMemo, useState, memo, useCallback } from "react";
import { Segmented } from "antd";
import {
  BulbOutlined,
  FieldTimeOutlined,
  ToolOutlined,
  BarChartOutlined,
} from "@ant-design/icons";

import { ThinkingChain } from "./ThinkingChain";
import { ActivityTimeline } from "./execution/ActivityTimeline";
import {
  ToolCallVisualization,
  type ToolExecutionItem,
} from "./execution/ToolCallVisualization";
import {
  TokenUsageChart,
  type TokenData,
  type CostData,
} from "./execution/TokenUsageChart";
import {
  adaptTimelineData,
  adaptToolVisualizationData,
  extractTokenData,
  hasExecutionData,
} from "../../utils/agentDataAdapters";
import type { Message } from "../../types/agent";

export type ViewType = "thinking" | "activity" | "tools" | "tokens";

export interface ExecutionDetailsPanelProps {
  /** Message data from store */
  message: Message;
  /** Whether the message is currently streaming */
  isStreaming?: boolean;
  /** Compact mode for smaller displays */
  compact?: boolean;
  /** Default view to show */
  defaultView?: ViewType;
  /** Show view selector */
  showViewSelector?: boolean;
}

/**
 * View option configuration
 */
interface ViewOption {
  value: ViewType;
  label: string;
  icon: React.ReactNode;
  available: boolean;
}

/**
 * ExecutionDetailsPanel component
 */
export const ExecutionDetailsPanel: React.FC<ExecutionDetailsPanelProps> = memo(({
  message,
  isStreaming = false,
  compact = false,
  defaultView = "thinking",
  showViewSelector = true,
}) => {
  const [currentView, setCurrentView] = useState<ViewType>(defaultView);

  // Memoized data transformations
  const timelineData = useMemo(() => adaptTimelineData(message), [message]);

  const toolVisualizationData = useMemo<ToolExecutionItem[]>(
    () => adaptToolVisualizationData(message),
    [message]
  );

  const tokenInfo = useMemo(() => extractTokenData(message), [message]);

  const hasData = useMemo(() => hasExecutionData(message), [message]);

  // Memoized ThinkingChain props
  const thinkingChainProps = useMemo(() => {
    return {
      thoughts: (message.metadata?.thoughts as string[]) || [],
      toolCalls: message.tool_calls,
      toolResults: message.tool_results,
      isThinking: isStreaming && message.content.length === 0,
      toolExecutions: message.metadata?.tool_executions as Record<
        string,
        { startTime?: number; endTime?: number; duration?: number }
      >,
      timeline: message.metadata?.timeline as any[],
    };
  }, [message, isStreaming]);

  // Determine which views are available
  const viewOptions = useMemo<ViewOption[]>(() => {
    const hasTimeline = timelineData.timeline.length > 0;
    const hasThoughts = thinkingChainProps.thoughts.length > 0;
    const hasToolCalls = (message.tool_calls?.length || 0) > 0;
    const hasTokens = tokenInfo.tokenData !== undefined;

    return [
      {
        value: "thinking" as ViewType,
        label: "Thinking",
        icon: <BulbOutlined />,
        available: hasTimeline || hasThoughts || hasToolCalls,
      },
      {
        value: "activity" as ViewType,
        label: "Activity",
        icon: <FieldTimeOutlined />,
        available: hasTimeline,
      },
      {
        value: "tools" as ViewType,
        label: "Tools",
        icon: <ToolOutlined />,
        available: toolVisualizationData.length > 0,
      },
      {
        value: "tokens" as ViewType,
        label: "Tokens",
        icon: <BarChartOutlined />,
        available: hasTokens,
      },
    ];
  }, [
    timelineData,
    thinkingChainProps,
    message.tool_calls,
    toolVisualizationData,
    tokenInfo,
  ]);

  // Filter to only available views
  const availableViews = useMemo(
    () => viewOptions.filter((opt) => opt.available),
    [viewOptions]
  );

  // Auto-switch to available view if current is not available
  const effectiveView = useMemo(() => {
    const isCurrentAvailable = availableViews.some(
      (v) => v.value === currentView
    );
    if (isCurrentAvailable) return currentView;
    // Fall back to first available or 'thinking'
    return availableViews[0]?.value || "thinking";
  }, [currentView, availableViews]);

  // Don't render if no execution data and not streaming
  if (!hasData && !isStreaming) {
    return null;
  }

  // Memoized view content to avoid re-creation on every render
  const viewContent = useMemo(() => {
    switch (effectiveView) {
      case "thinking":
        return <ThinkingChain {...thinkingChainProps} />;

      case "activity":
        return (
          <ActivityTimeline
            timeline={timelineData.timeline}
            toolExecutions={timelineData.toolExecutions}
            toolResults={timelineData.toolResults}
            isActive={isStreaming}
            compact={compact}
            autoScroll={isStreaming}
          />
        );

      case "tools":
        return (
          <ToolCallVisualization
            toolExecutions={toolVisualizationData}
            mode="grid"
            showDetails={true}
            allowModeSwitch={!compact}
            compact={compact}
          />
        );

      case "tokens":
        if (!tokenInfo.tokenData) return null;
        return (
          <TokenUsageChart
            tokenData={tokenInfo.tokenData as TokenData}
            costData={tokenInfo.costData as CostData | undefined}
            variant={compact ? "compact" : "detailed"}
          />
        );

      default:
        return <ThinkingChain {...thinkingChainProps} />;
    }
  }, [effectiveView, thinkingChainProps, timelineData, isStreaming, compact, toolVisualizationData, tokenInfo]);

  // Single view mode (no selector)
  if (!showViewSelector || availableViews.length <= 1) {
    return <div className="w-full">{viewContent}</div>;
  }

  // Memoized segmented options to avoid re-creation on every render
  const segmentedOptions = useMemo(() =>
    availableViews.map((opt) => ({
      value: opt.value,
      label: (
        <div className="flex items-center gap-1.5 px-1">
          {opt.icon}
          {!compact && <span className="text-xs">{opt.label}</span>}
        </div>
      ),
    })),
    [availableViews, compact]
  );

  // Handle view change with useCallback for optimization
  const handleViewChange = useCallback((value: string | number) => {
    setCurrentView(value as ViewType);
  }, []);

  return (
    <div className="w-full space-y-3">
      {/* View selector */}
      <div className="flex justify-start">
        <Segmented
          size="small"
          value={effectiveView}
          onChange={handleViewChange}
          options={segmentedOptions}
          className="bg-slate-100 dark:bg-slate-800"
        />
      </div>

      {/* View content */}
      <div className="w-full">{viewContent}</div>
    </div>
  );
});

ExecutionDetailsPanel.displayName = 'ExecutionDetailsPanel';

export default ExecutionDetailsPanel;
