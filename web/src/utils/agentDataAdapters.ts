/**
 * Agent Data Adapters
 *
 * Utility functions to transform Store data to component props.
 * These adapters ensure data compatibility between agent store
 * and the visualization components.
 */

import type {
  TimelineItem,
  ToolExecutionInfo,
} from '../components/agent/execution/ActivityTimeline';
import type { TokenData, CostData } from '../components/agent/execution/TokenUsageChart';
import type { ToolExecutionItem } from '../components/agent/execution/ToolCallVisualization';
import type { Message, ToolCall, ToolResult } from '../types/agent';

/**
 * Adapt message data for ActivityTimeline component
 */
export function adaptTimelineData(message: Message): {
  timeline: TimelineItem[];
  toolExecutions: Record<string, ToolExecutionInfo>;
  toolCalls: ToolCall[];
  toolResults: ToolResult[];
} {
  return {
    timeline: (message.metadata?.timeline as TimelineItem[]) || [],
    toolExecutions: (message.metadata?.tool_executions as Record<string, ToolExecutionInfo>) || {},
    toolCalls: message.tool_calls || [],
    toolResults: message.tool_results || [],
  };
}

/**
 * Adapt message data for ToolCallVisualization component
 */
export function adaptToolVisualizationData(message: Message): ToolExecutionItem[] {
  const timeline = (message.metadata?.timeline as TimelineItem[]) || [];
  const executions = (message.metadata?.tool_executions as Record<string, ToolExecutionInfo>) || {};
  const results = message.tool_results || [];

  // Filter timeline items to get only tool calls
  const toolCallItems = timeline.filter((item) => item.type === 'tool_call');

  // If no timeline items, try to build from tool_calls
  if (toolCallItems.length === 0 && message.tool_calls) {
    return message.tool_calls.map((call, index) => {
      const result = results.find((r) => r.tool_name === call.name);
      const execution = executions[call.name];

      return {
        id: `tool-${call.name}-${index}`,
        toolName: call.name,
        input: call.arguments || {},
        output: result?.result,
        status: result
          ? result.error
            ? ('failed' as const)
            : ('success' as const)
          : ('running' as const),
        startTime: execution?.startTime || Date.now(),
        endTime: execution?.endTime,
        duration: execution?.duration,
        stepNumber: index + 1,
        error: result?.error,
      };
    });
  }

  return toolCallItems.map((item, index) => {
    const toolName = item.toolName || 'unknown';
    const execution = executions[toolName];
    const result = results.find((r) => r.tool_name === toolName);

    return {
      id: item.id,
      toolName,
      input: item.toolInput || {},
      output: result?.result,
      status: result
        ? result.error
          ? ('failed' as const)
          : ('success' as const)
        : ('running' as const),
      startTime: execution?.startTime || item.timestamp,
      endTime: execution?.endTime,
      duration: execution?.duration,
      stepNumber: index + 1,
      error: result?.error,
    };
  });
}

/**
 * Extract token usage data from message (graceful degradation)
 *
 * Supports multiple possible field names from different LLM providers:
 * - token_usage (standard)
 * - usage (OpenAI style)
 * - llm_usage (custom)
 */
export function extractTokenData(message: Message): {
  tokenData?: TokenData | undefined;
  costData?: CostData | undefined;
} {
  const metadata = message.metadata;

  if (!metadata) return {};

  // Check multiple possible field names
  const tokenUsage =
    (metadata.token_usage as Record<string, number | undefined>) ||
    (metadata.usage as Record<string, number | undefined>) ||
    (metadata.llm_usage as Record<string, number | undefined>);

  if (!tokenUsage) return {};

  // Extract token counts (support both naming conventions)
  const inputTokens = tokenUsage.input_tokens || tokenUsage.prompt_tokens || 0;
  const outputTokens = tokenUsage.output_tokens || tokenUsage.completion_tokens || 0;
  const reasoningTokens = tokenUsage.reasoning_tokens;
  const totalTokens =
    tokenUsage.total_tokens || inputTokens + outputTokens + (reasoningTokens || 0);

  // Skip if no meaningful data
  if (totalTokens === 0) return {};

  const tokenData: TokenData = {
    input: inputTokens,
    output: outputTokens,
    reasoning: reasoningTokens,
    total: totalTokens,
  };

  // Extract cost data if available
  const costMetadata = metadata.cost as
    | {
        total?: number | undefined;
        breakdown?:
          | {
              input_cost?: number | undefined;
              output_cost?: number | undefined;
              reasoning_cost?: number | undefined;
            }
          | undefined;
      }
    | undefined;

  // Build costData only if we have valid breakdown data
  let costData: CostData | undefined;
  if (costMetadata) {
    const breakdown =
      costMetadata.breakdown &&
      costMetadata.breakdown.input_cost !== undefined &&
      costMetadata.breakdown.output_cost !== undefined
        ? {
            input_cost: costMetadata.breakdown.input_cost,
            output_cost: costMetadata.breakdown.output_cost,
            reasoning_cost: costMetadata.breakdown.reasoning_cost,
          }
        : undefined;

    costData = {
      total: costMetadata.total || 0,
      breakdown,
    };
  }

  return { tokenData, costData };
}

/**
 * Check if message has any execution data worth displaying
 */
export function hasExecutionData(message: Message): boolean {
  const timeline = (message.metadata?.timeline as TimelineItem[]) || [];
  const thoughts = (message.metadata?.thoughts as string[]) || [];
  const toolCalls = message.tool_calls || [];

  return timeline.length > 0 || thoughts.length > 0 || toolCalls.length > 0;
}
