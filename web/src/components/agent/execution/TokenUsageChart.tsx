/**
 * TokenUsageChart - Token usage visualization chart
 *
 * Displays token usage and cost information as a visual chart with:
 * - Stacked horizontal bar showing input/output/reasoning tokens
 * - Cost breakdown (optional)
 * - Compact and detailed display modes
 * - Dark mode support
 */

import React, { useState, useMemo } from "react";
import { Tooltip } from "antd";
import {
  InfoCircleOutlined,
  DownOutlined,
  RightOutlined,
  DollarOutlined,
} from "@ant-design/icons";

/**
 * Token usage data structure
 */
export interface TokenData {
  input: number;
  output: number;
  reasoning?: number;
  total: number;
}

/**
 * Cost data structure
 */
export interface CostData {
  total: number;
  breakdown?: {
    input_cost: number;
    output_cost: number;
    reasoning_cost?: number;
  };
}

export interface TokenUsageChartProps {
  /** Token usage data */
  tokenData: TokenData;
  /** Cost data (optional) */
  costData?: CostData;
  /** Display mode */
  variant?: "compact" | "detailed";
  /** Maximum tokens for percentage calculation (optional) */
  maxTokens?: number;
  /** Show trend indicator (requires historical data) */
  showTrend?: boolean;
  /** Threshold percentage for warning state */
  warningThreshold?: number;
}

// Color scheme for token types - aligned with design tokens
const COLORS = {
  input: {
    bg: "bg-blue-500",
    bgLight: "bg-blue-100 dark:bg-blue-900/30",
    text: "text-blue-600 dark:text-blue-400",
    border: "border-blue-300 dark:border-blue-700",
    hex: "#3b82f6", // Secondary color
  },
  output: {
    bg: "bg-emerald-500",
    bgLight: "bg-emerald-100 dark:bg-emerald-900/30",
    text: "text-emerald-600 dark:text-emerald-400",
    border: "border-emerald-300 dark:border-emerald-700",
    hex: "#10b981", // Success color
  },
  reasoning: {
    bg: "bg-purple-500",
    bgLight: "bg-purple-100 dark:bg-purple-900/30",
    text: "text-purple-600 dark:text-purple-400",
    border: "border-purple-300 dark:border-purple-700",
    hex: "#8b5cf6", // Purple for reasoning
  },
};

// Format number with locale separators
const formatNumber = (num: number): string => {
  return num.toLocaleString();
};

// Format cost with appropriate precision
const formatCost = (cost: number): string => {
  if (cost < 0.0001) return "$0.0000";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
};

/**
 * Stacked bar component for token visualization
 */
interface StackedBarProps {
  input: number;
  output: number;
  reasoning?: number;
  total: number;
  maxTokens?: number;
  showLabels?: boolean;
}

const StackedBar: React.FC<StackedBarProps> = ({
  input,
  output,
  reasoning = 0,
  total,
  maxTokens,
  showLabels = false,
}) => {
  const effectiveMax = maxTokens || total;
  const inputPercent = (input / effectiveMax) * 100;
  const outputPercent = (output / effectiveMax) * 100;
  const reasoningPercent = (reasoning / effectiveMax) * 100;
  const totalPercent = (total / effectiveMax) * 100;

  return (
    <div className="w-full">
      {/* Progress bar container */}
      <div className="relative h-3 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
        <div className="absolute inset-0 flex">
          {/* Input segment */}
          <Tooltip title={`Input: ${formatNumber(input)} tokens`}>
            <div
              className={`${COLORS.input.bg} transition-all duration-500`}
              style={{ width: `${inputPercent}%` }}
            />
          </Tooltip>
          {/* Output segment */}
          <Tooltip title={`Output: ${formatNumber(output)} tokens`}>
            <div
              className={`${COLORS.output.bg} transition-all duration-500`}
              style={{ width: `${outputPercent}%` }}
            />
          </Tooltip>
          {/* Reasoning segment */}
          {reasoning > 0 && (
            <Tooltip title={`Reasoning: ${formatNumber(reasoning)} tokens`}>
              <div
                className={`${COLORS.reasoning.bg} transition-all duration-500`}
                style={{ width: `${reasoningPercent}%` }}
              />
            </Tooltip>
          )}
        </div>
      </div>

      {/* Labels */}
      {showLabels && (
        <div className="flex justify-between mt-1 text-[10px] text-slate-500 dark:text-slate-400">
          <span>0</span>
          {maxTokens && (
            <span className="font-medium">
              {Math.round(totalPercent)}% used
            </span>
          )}
          <span>{formatNumber(effectiveMax)}</span>
        </div>
      )}
    </div>
  );
};

/**
 * Legend item component
 */
interface LegendItemProps {
  color: string;
  label: string;
  value: number;
  percentage: number;
}

const LegendItem: React.FC<LegendItemProps> = ({
  color,
  label,
  value,
  percentage,
}) => {
  return (
    <div className="flex items-center gap-2">
      <div className={`w-3 h-3 rounded-sm ${color}`} />
      <span className="text-xs text-slate-600 dark:text-slate-300">
        {label}
      </span>
      <span className="text-xs font-mono text-slate-700 dark:text-slate-200 ml-auto">
        {formatNumber(value)}
      </span>
      <span className="text-[10px] text-slate-400 dark:text-slate-500 w-10 text-right">
        ({percentage.toFixed(0)}%)
      </span>
    </div>
  );
};

/**
 * TokenUsageChart component
 */
export const TokenUsageChart: React.FC<TokenUsageChartProps> = ({
  tokenData,
  costData,
  variant = "compact",
  maxTokens,
  warningThreshold = 90,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // Calculate percentages
  const percentages = useMemo(() => {
    const { input, output, reasoning = 0, total } = tokenData;
    return {
      input: total > 0 ? (input / total) * 100 : 0,
      output: total > 0 ? (output / total) * 100 : 0,
      reasoning: total > 0 ? (reasoning / total) * 100 : 0,
      total: maxTokens ? (total / maxTokens) * 100 : 100,
    };
  }, [tokenData, maxTokens]);

  // Check if over warning threshold
  const isOverThreshold = maxTokens && percentages.total >= warningThreshold;

  // Don't render if no data
  if (tokenData.total === 0) {
    return null;
  }

  // Compact variant - inline display
  if (variant === "compact") {
    return (
      <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-1 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
        >
          {isExpanded ? (
            <DownOutlined className="text-[10px]" />
          ) : (
            <RightOutlined className="text-[10px]" />
          )}
          <span
            className={
              isOverThreshold ? "text-amber-600 dark:text-amber-400" : ""
            }
          >
            {formatNumber(tokenData.total)} tokens
          </span>
          {costData && (
            <>
              <span>·</span>
              <span>{formatCost(costData.total)}</span>
            </>
          )}
        </button>

        {isExpanded && (
          <div className="flex-1 max-w-[200px]">
            <StackedBar {...tokenData} maxTokens={maxTokens} />
          </div>
        )}
      </div>
    );
  }

  // Detailed variant - card display
  return (
    <div className="p-4 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
            <InfoCircleOutlined className="text-blue-500" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              Token Usage
            </h3>
            {costData && (
              <p className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1">
                <DollarOutlined />
                {formatCost(costData.total)}
              </p>
            )}
          </div>
        </div>

        {/* Total badge */}
        <div
          className={`px-3 py-1 rounded-full text-sm font-mono ${
            isOverThreshold
              ? "bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400"
              : "bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200"
          }`}
        >
          {formatNumber(tokenData.total)}
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-4">
        <StackedBar
          {...tokenData}
          maxTokens={maxTokens}
          showLabels={!!maxTokens}
        />
      </div>

      {/* Legend / Breakdown */}
      <div className="space-y-2">
        <LegendItem
          color={COLORS.input.bg}
          label="Input"
          value={tokenData.input}
          percentage={percentages.input}
        />
        <LegendItem
          color={COLORS.output.bg}
          label="Output"
          value={tokenData.output}
          percentage={percentages.output}
        />
        {tokenData.reasoning !== undefined && tokenData.reasoning > 0 && (
          <LegendItem
            color={COLORS.reasoning.bg}
            label="Reasoning"
            value={tokenData.reasoning}
            percentage={percentages.reasoning}
          />
        )}
      </div>

      {/* Cost breakdown */}
      {costData?.breakdown && (
        <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700">
          <h4 className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-2">
            Cost Breakdown
          </h4>
          <div className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-slate-600 dark:text-slate-300">
                Input cost:
              </span>
              <span className="font-mono text-slate-700 dark:text-slate-200">
                {formatCost(costData.breakdown.input_cost)}
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-600 dark:text-slate-300">
                Output cost:
              </span>
              <span className="font-mono text-slate-700 dark:text-slate-200">
                {formatCost(costData.breakdown.output_cost)}
              </span>
            </div>
            {costData.breakdown.reasoning_cost !== undefined && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-600 dark:text-slate-300">
                  Reasoning cost:
                </span>
                <span className="font-mono text-slate-700 dark:text-slate-200">
                  {formatCost(costData.breakdown.reasoning_cost)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Warning message */}
      {isOverThreshold && (
        <div className="mt-4 p-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Token usage is above {warningThreshold}% of the limit.
          </p>
        </div>
      )}
    </div>
  );
};

export default TokenUsageChart;
