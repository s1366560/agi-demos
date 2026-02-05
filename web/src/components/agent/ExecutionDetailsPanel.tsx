/**
 * ExecutionDetailsPanel - Compound Component for Execution Details Display
 *
 * ## Usage
 *
 * ### Convenience Usage (Default rendering)
 * ```tsx
 * <ExecutionDetailsPanel message={message} />
 * ```
 *
 * ### Compound Components (Custom rendering)
 * ```tsx
 * <ExecutionDetailsPanel message={message}>
 *   <ExecutionDetailsPanel.Thinking />
 *   <ExecutionDetailsPanel.Activity />
 *   <ExecutionDetailsPanel.Tools />
 * </ExecutionDetailsPanel>
 * ```
 *
 * ### Namespace Usage
 * ```tsx
 * <ExecutionDetailsPanel.Root message={message}>
 *   <ExecutionDetailsPanel.Tokens />
 * </ExecutionDetailsPanel.Root>
 * ```
 */

import React, { useMemo, useState, memo, useCallback, Children } from "react";

import {
  BulbOutlined,
  FieldTimeOutlined,
  ToolOutlined,
  BarChartOutlined,
} from "@ant-design/icons";
import { Segmented } from "antd";

import {
  adaptTimelineData,
  adaptToolVisualizationData,
  extractTokenData,
  hasExecutionData,
} from "../../utils/agentDataAdapters";

import { ActivityTimeline } from "./execution/ActivityTimeline";
import {
  TokenUsageChart,
  type TokenData,
  type CostData,
} from "./execution/TokenUsageChart";
import {
  ToolCallVisualization,
  type ToolExecutionItem,
} from "./execution/ToolCallVisualization";
import { ThinkingChain } from "./ThinkingChain";


import type {
  ViewType,
  ExecutionDetailsPanelRootProps,
  ExecutionThinkingProps,
  ExecutionActivityProps,
  ExecutionToolsProps,
  ExecutionTokensProps,
  ExecutionViewSelectorProps,
  ExecutionDetailsPanelCompound,
} from "./executionTypes";

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const THINKING_SYMBOL = Symbol("ExecutionDetailsPanelThinking");
const ACTIVITY_SYMBOL = Symbol("ExecutionDetailsPanelActivity");
const TOOLS_SYMBOL = Symbol("ExecutionDetailsPanelTools");
const TOKENS_SYMBOL = Symbol("ExecutionDetailsPanelTokens");
const SELECTOR_SYMBOL = Symbol("ExecutionDetailsPanelViewSelector");

// ========================================
// View Option Configuration
// ========================================

interface ViewOption {
  value: ViewType;
  label: string;
  icon: React.ReactNode;
  available: boolean;
}

// ========================================
// Main Component
// ========================================

const ExecutionDetailsPanelInner: React.FC<ExecutionDetailsPanelRootProps> = ({
  message,
  isStreaming = false,
  compact = false,
  defaultView = "thinking",
  showViewSelector = true,
  children,
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

  // Parse children to detect sub-components
  const childrenArray = Children.toArray(children);
  const thinkingChild = childrenArray.find(
    (child: any) => child?.type?.[THINKING_SYMBOL]
  ) as any;
  const activityChild = childrenArray.find(
    (child: any) => child?.type?.[ACTIVITY_SYMBOL]
  ) as any;
  const toolsChild = childrenArray.find(
    (child: any) => child?.type?.[TOOLS_SYMBOL]
  ) as any;
  const tokensChild = childrenArray.find(
    (child: any) => child?.type?.[TOKENS_SYMBOL]
  ) as any;
  const selectorChild = childrenArray.find(
    (child: any) => child?.type?.[SELECTOR_SYMBOL]
  ) as any;

  // Determine if using compound mode
  const hasSubComponents =
    thinkingChild || activityChild || toolsChild || tokensChild || selectorChild;

  // In legacy mode, include all views by default
  // In compound mode, only include explicitly specified views
  const includeThinking = hasSubComponents ? !!thinkingChild : true;
  const includeActivity = hasSubComponents ? !!activityChild : true;
  const includeTools = hasSubComponents ? !!toolsChild : true;
  const includeTokens = hasSubComponents ? !!tokensChild : true;

  // Count included views for selector logic
  const includedViewCount = [includeThinking, includeActivity, includeTools, includeTokens]
    .filter(Boolean).length;

  // View selector logic:
  // - In legacy mode: respect showViewSelector
  // - In compound mode with ViewSelector: respect showViewSelector
  // - In compound mode without ViewSelector: show only if multiple views included and prop is true
  const includeSelector = !hasSubComponents || !!selectorChild
    ? showViewSelector
    : showViewSelector && includedViewCount > 1;

  // Determine which views are available
  const viewOptions = useMemo<ViewOption[]>(() => {
    const hasTimeline = timelineData.timeline.length > 0;
    const hasThoughts = thinkingChainProps.thoughts.length > 0;
    const hasToolCalls = (message.tool_calls?.length || 0) > 0;
    const hasTokens = tokenInfo.tokenData !== undefined;

    // All potential views
    const allViews = [
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

    // In compound mode, only include views for which sub-components are provided
    if (hasSubComponents) {
      return allViews.filter((view) => {
        if (view.value === "thinking") return !!thinkingChild;
        if (view.value === "activity") return !!activityChild;
        if (view.value === "tools") return !!toolsChild;
        if (view.value === "tokens") return !!tokensChild;
        return false;
      });
    }

    return allViews;
  }, [
    hasSubComponents,
    thinkingChild,
    activityChild,
    toolsChild,
    tokensChild,
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

  // Handle view change
  const handleViewChange = useCallback((value: string | number) => {
    setCurrentView(value as ViewType);
  }, []);

  // Render view content based on effectiveView
  const renderViewContent = () => {
    switch (effectiveView) {
      case "thinking":
        return includeThinking ? <ThinkingChain {...thinkingChainProps} /> : null;

      case "activity":
        return includeActivity ? (
          <ActivityTimeline
            timeline={timelineData.timeline}
            toolExecutions={timelineData.toolExecutions}
            toolResults={timelineData.toolResults}
            isActive={isStreaming}
            compact={compact}
            autoScroll={isStreaming}
          />
        ) : null;

      case "tools":
        return includeTools ? (
          <ToolCallVisualization
            toolExecutions={toolVisualizationData}
            mode="grid"
            showDetails={true}
            allowModeSwitch={!compact}
            compact={compact}
          />
        ) : null;

      case "tokens":
        return includeTokens && tokenInfo.tokenData ? (
          <TokenUsageChart
            tokenData={tokenInfo.tokenData as TokenData}
            costData={tokenInfo.costData as CostData | undefined}
            variant={compact ? "compact" : "detailed"}
          />
        ) : null;

      default:
        return <ThinkingChain {...thinkingChainProps} />;
    }
  };

  // Memoized segmented options
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

  // Don't render if no execution data and not streaming
  if (!hasData && !isStreaming) {
    return null;
  }

  const viewContent = renderViewContent();

  // No content to render
  if (!viewContent) {
    return null;
  }

  // Single view mode (no selector)
  if (!includeSelector || availableViews.length <= 1) {
    return <div className="w-full">{viewContent}</div>;
  }

  return (
    <div className="w-full space-y-3">
      {/* View selector */}
      {includeSelector && (
        <div className="flex justify-start">
          <Segmented
            size="small"
            value={effectiveView}
            onChange={handleViewChange}
            options={segmentedOptions}
            className="bg-slate-100 dark:bg-slate-800"
          />
        </div>
      )}

      {/* View content */}
      <div className="w-full">{viewContent}</div>
    </div>
  );
};

// ========================================
// Sub-Components (Marker Components)
// ========================================

const ThinkingMarker = function ExecutionDetailsPanelThinkingMarker(_props: ExecutionThinkingProps) {
  return null;
};
(ThinkingMarker as any)[THINKING_SYMBOL] = true;

const ActivityMarker = function ExecutionDetailsPanelActivityMarker(_props: ExecutionActivityProps) {
  return null;
};
(ActivityMarker as any)[ACTIVITY_SYMBOL] = true;

const ToolsMarker = function ExecutionDetailsPanelToolsMarker(_props: ExecutionToolsProps) {
  return null;
};
(ToolsMarker as any)[TOOLS_SYMBOL] = true;

const TokensMarker = function ExecutionDetailsPanelTokensMarker(_props: ExecutionTokensProps) {
  return null;
};
(TokensMarker as any)[TOKENS_SYMBOL] = true;

const ViewSelectorMarker = function ExecutionDetailsPanelViewSelectorMarker(_props: ExecutionViewSelectorProps) {
  return null;
};
(ViewSelectorMarker as any)[SELECTOR_SYMBOL] = true;

// Set display names for testing
(ThinkingMarker as any).displayName = "ExecutionDetailsPanelThinking";
(ActivityMarker as any).displayName = "ExecutionDetailsPanelActivity";
(ToolsMarker as any).displayName = "ExecutionDetailsPanelTools";
(TokensMarker as any).displayName = "ExecutionDetailsPanelTokens";
(ViewSelectorMarker as any).displayName = "ExecutionDetailsPanelViewSelector";

// Create compound component with sub-components
const ExecutionDetailsPanelMemo = memo(ExecutionDetailsPanelInner);
ExecutionDetailsPanelMemo.displayName = "ExecutionDetailsPanel";

// Create compound component object
const ExecutionDetailsPanelCompound = ExecutionDetailsPanelMemo as unknown as ExecutionDetailsPanelCompound;
ExecutionDetailsPanelCompound.Thinking = ThinkingMarker;
ExecutionDetailsPanelCompound.Activity = ActivityMarker;
ExecutionDetailsPanelCompound.Tools = ToolsMarker;
ExecutionDetailsPanelCompound.Tokens = TokensMarker;
ExecutionDetailsPanelCompound.ViewSelector = ViewSelectorMarker;
ExecutionDetailsPanelCompound.Root = ExecutionDetailsPanelMemo;

// Export compound component
export const ExecutionDetailsPanel = ExecutionDetailsPanelCompound;

export default ExecutionDetailsPanel;
