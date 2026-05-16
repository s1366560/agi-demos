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

import React, { useMemo, useState, memo, useCallback, Children } from 'react';

import { Segmented } from 'antd';
import { BarChart3, Clock, Lightbulb, Wrench } from 'lucide-react';

import {
  adaptTimelineData,
  adaptToolVisualizationData,
  extractTokenData,
  hasExecutionData,
} from '../../utils/agentDataAdapters';

import {
  ActivityTimeline,
  type TimelineItem,
  type ToolExecutionInfo,
} from './execution/ActivityTimeline';
import { TokenUsageChart } from './execution/TokenUsageChart';
import { ToolCallVisualization, type ToolExecutionItem } from './execution/ToolCallVisualization';
import { ThinkingChain } from './ThinkingChain';

import type {
  ViewType,
  ExecutionDetailsPanelRootProps,
  ExecutionThinkingProps,
  ExecutionActivityProps,
  ExecutionToolsProps,
  ExecutionTokensProps,
  ExecutionViewSelectorProps,
  ExecutionDetailsPanelCompound,
} from './executionTypes';

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const THINKING_SYMBOL = Symbol('ExecutionDetailsPanelThinking');
const ACTIVITY_SYMBOL = Symbol('ExecutionDetailsPanelActivity');
const TOOLS_SYMBOL = Symbol('ExecutionDetailsPanelTools');
const TOKENS_SYMBOL = Symbol('ExecutionDetailsPanelTokens');
const SELECTOR_SYMBOL = Symbol('ExecutionDetailsPanelViewSelector');

type MarkerSymbol =
  | typeof THINKING_SYMBOL
  | typeof ACTIVITY_SYMBOL
  | typeof TOOLS_SYMBOL
  | typeof TOKENS_SYMBOL
  | typeof SELECTOR_SYMBOL;

type MarkedComponent<P> = React.FC<P> & Partial<Record<MarkerSymbol, true>>;
type MarkableElementType = React.JSXElementConstructor<unknown> &
  Partial<Record<MarkerSymbol, true>>;

const markComponent = <P,>(
  component: React.FC<P>,
  marker: MarkerSymbol,
  displayName: string
): MarkedComponent<P> => {
  const marked = component as MarkedComponent<P>;
  marked[marker] = true;
  marked.displayName = displayName;
  return marked;
};

const hasMarker = <P,>(
  child: React.ReactNode,
  marker: MarkerSymbol
): child is React.ReactElement<P> => {
  if (!React.isValidElement(child) || typeof child.type === 'string') {
    return false;
  }

  return Boolean((child.type as MarkableElementType)[marker]);
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const toTimeline = (value: unknown): TimelineItem[] =>
  Array.isArray(value)
    ? value.filter((item): item is TimelineItem => {
        if (!isRecord(item)) return false;
        return (
          (item.type === 'thought' || item.type === 'tool_call') &&
          typeof item.id === 'string' &&
          typeof item.timestamp === 'number'
        );
      })
    : [];

const toToolExecutions = (value: unknown): Record<string, ToolExecutionInfo> | undefined => {
  if (!isRecord(value)) return undefined;

  const entries = Object.entries(value).flatMap(([key, item]) => {
    if (!isRecord(item)) return [];

    const execution: ToolExecutionInfo = {
      startTime: typeof item.startTime === 'number' ? item.startTime : undefined,
      endTime: typeof item.endTime === 'number' ? item.endTime : undefined,
      duration: typeof item.duration === 'number' ? item.duration : undefined,
    };

    return [[key, execution] as const];
  });

  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
};

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
  defaultView = 'thinking',
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
      thoughts: toStringArray(message.metadata?.thoughts),
      toolCalls: message.tool_calls,
      toolResults: message.tool_results,
      isThinking: isStreaming && message.content.length === 0,
      toolExecutions: toToolExecutions(message.metadata?.tool_executions),
      timeline: toTimeline(message.metadata?.timeline),
    };
  }, [message, isStreaming]);

  // Parse children to detect sub-components
  const childrenArray = Children.toArray(children);
  const thinkingChild = childrenArray.find(
    (child): child is React.ReactElement<ExecutionThinkingProps> =>
      hasMarker<ExecutionThinkingProps>(child, THINKING_SYMBOL)
  );
  const activityChild = childrenArray.find(
    (child): child is React.ReactElement<ExecutionActivityProps> =>
      hasMarker<ExecutionActivityProps>(child, ACTIVITY_SYMBOL)
  );
  const toolsChild = childrenArray.find((child): child is React.ReactElement<ExecutionToolsProps> =>
    hasMarker<ExecutionToolsProps>(child, TOOLS_SYMBOL)
  );
  const tokensChild = childrenArray.find(
    (child): child is React.ReactElement<ExecutionTokensProps> =>
      hasMarker<ExecutionTokensProps>(child, TOKENS_SYMBOL)
  );
  const selectorChild = childrenArray.find(
    (child): child is React.ReactElement<ExecutionViewSelectorProps> =>
      hasMarker<ExecutionViewSelectorProps>(child, SELECTOR_SYMBOL)
  );

  // Determine if using compound mode
  const hasSubComponents = Boolean(
    thinkingChild ?? activityChild ?? toolsChild ?? tokensChild ?? selectorChild
  );

  // In legacy mode, include all views by default
  // In compound mode, only include explicitly specified views
  const includeThinking = hasSubComponents ? thinkingChild !== undefined : true;
  const includeActivity = hasSubComponents ? activityChild !== undefined : true;
  const includeTools = hasSubComponents ? toolsChild !== undefined : true;
  const includeTokens = hasSubComponents ? tokensChild !== undefined : true;

  // Count included views for selector logic
  const includedViewCount = [includeThinking, includeActivity, includeTools, includeTokens].filter(
    Boolean
  ).length;

  // View selector logic:
  // - In legacy mode: respect showViewSelector
  // - In compound mode with ViewSelector: respect showViewSelector
  // - In compound mode without ViewSelector: show only if multiple views included and prop is true
  const includeSelector =
    !hasSubComponents || selectorChild !== undefined
      ? showViewSelector
      : showViewSelector && includedViewCount > 1;

  // Determine which views are available
  const viewOptions = useMemo<ViewOption[]>(() => {
    const hasTimeline = timelineData.timeline.length > 0;
    const hasThoughts = thinkingChainProps.thoughts.length > 0;
    const hasToolCalls = (message.tool_calls?.length || 0) > 0;
    const hasTokens = tokenInfo.tokenData !== undefined;

    // All potential views
    const allViews: ViewOption[] = [
      {
        value: 'thinking' as ViewType,
        label: 'Thinking',
        icon: <Lightbulb size={16} />,
        available: hasTimeline || hasThoughts || hasToolCalls,
      },
      {
        value: 'activity' as ViewType,
        label: 'Activity',
        icon: <Clock size={16} />,
        available: hasTimeline,
      },
      {
        value: 'tools' as ViewType,
        label: 'Tools',
        icon: <Wrench size={16} />,
        available: toolVisualizationData.length > 0,
      },
      {
        value: 'tokens' as ViewType,
        label: 'Tokens',
        icon: <BarChart3 size={16} />,
        available: hasTokens,
      },
    ];

    // In compound mode, only include views for which sub-components are provided
    if (hasSubComponents) {
      const includedViews: Record<ViewType, boolean> = {
        thinking: thinkingChild !== undefined,
        activity: activityChild !== undefined,
        tools: toolsChild !== undefined,
        tokens: tokensChild !== undefined,
      };

      return allViews.filter((view) => includedViews[view.value]);
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
  const availableViews = useMemo(() => viewOptions.filter((opt) => opt.available), [viewOptions]);

  // Auto-switch to available view if current is not available
  const effectiveView = useMemo(() => {
    const isCurrentAvailable = availableViews.some((v) => v.value === currentView);
    if (isCurrentAvailable) return currentView;
    // Fall back to first available or 'thinking'
    return availableViews[0]?.value || 'thinking';
  }, [currentView, availableViews]);

  // Handle view change
  const handleViewChange = useCallback((value: string | number) => {
    setCurrentView(value as ViewType);
  }, []);

  // Render view content based on effectiveView
  const renderViewContent = () => {
    switch (effectiveView) {
      case 'thinking':
        return includeThinking ? <ThinkingChain {...thinkingChainProps} /> : null;

      case 'activity':
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

      case 'tools':
        return includeTools ? (
          <ToolCallVisualization
            toolExecutions={toolVisualizationData}
            mode="grid"
            showDetails={true}
            allowModeSwitch={!compact}
            compact={compact}
          />
        ) : null;

      case 'tokens':
        return includeTokens && tokenInfo.tokenData ? (
          <TokenUsageChart
            tokenData={tokenInfo.tokenData}
            costData={tokenInfo.costData}
            variant={compact ? 'compact' : 'detailed'}
          />
        ) : null;

      default:
        return <ThinkingChain {...thinkingChainProps} />;
    }
  };

  // Memoized segmented options
  const segmentedOptions = useMemo(
    () =>
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
};

// ========================================
// Sub-Components (Marker Components)
// ========================================

const ThinkingMarker = markComponent(
  function ExecutionDetailsPanelThinkingMarker(_props: ExecutionThinkingProps) {
    return null;
  },
  THINKING_SYMBOL,
  'ExecutionDetailsPanelThinking'
);

const ActivityMarker = markComponent(
  function ExecutionDetailsPanelActivityMarker(_props: ExecutionActivityProps) {
    return null;
  },
  ACTIVITY_SYMBOL,
  'ExecutionDetailsPanelActivity'
);

const ToolsMarker = markComponent(
  function ExecutionDetailsPanelToolsMarker(_props: ExecutionToolsProps) {
    return null;
  },
  TOOLS_SYMBOL,
  'ExecutionDetailsPanelTools'
);

const TokensMarker = markComponent(
  function ExecutionDetailsPanelTokensMarker(_props: ExecutionTokensProps) {
    return null;
  },
  TOKENS_SYMBOL,
  'ExecutionDetailsPanelTokens'
);

const ViewSelectorMarker = markComponent(
  function ExecutionDetailsPanelViewSelectorMarker(_props: ExecutionViewSelectorProps) {
    return null;
  },
  SELECTOR_SYMBOL,
  'ExecutionDetailsPanelViewSelector'
);

// Create compound component with sub-components
const ExecutionDetailsPanelMemo = memo(ExecutionDetailsPanelInner);
ExecutionDetailsPanelMemo.displayName = 'ExecutionDetailsPanel';

// Create compound component object
const ExecutionDetailsPanelCompound =
  ExecutionDetailsPanelMemo as unknown as ExecutionDetailsPanelCompound;
ExecutionDetailsPanelCompound.Thinking = ThinkingMarker;
ExecutionDetailsPanelCompound.Activity = ActivityMarker;
ExecutionDetailsPanelCompound.Tools = ToolsMarker;
ExecutionDetailsPanelCompound.Tokens = TokensMarker;
ExecutionDetailsPanelCompound.ViewSelector = ViewSelectorMarker;
ExecutionDetailsPanelCompound.Root = ExecutionDetailsPanelMemo;

// Export compound component
export const ExecutionDetailsPanel = ExecutionDetailsPanelCompound;

export default ExecutionDetailsPanel;
