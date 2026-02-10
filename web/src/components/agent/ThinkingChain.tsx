/**
 * ThinkingChain component
 *
 * Displays the agent's thinking process with timeline visualization.
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 * Only re-renders when timeline, thoughts, toolCalls, or toolResults change.
 */

import React, { memo, useMemo } from 'react';

import { BulbOutlined, ToolOutlined } from '@ant-design/icons';
import { Collapse } from 'antd';

import { formatTimeOnly } from '@/utils/date';
import { ToolCall, ToolResult } from '../../types/agent';

import { ToolCard } from './ToolCard';

interface TimelineItem {
  type: 'thought' | 'tool_call';
  id: string;
  content?: string;
  toolName?: string;
  toolInput?: any;
  timestamp: number;
}

interface ThinkingChainProps {
  thoughts: string[]; // Keep for backward compatibility or simple views
  toolCalls?: ToolCall[];
  toolResults?: ToolResult[];
  isThinking?: boolean;
  toolExecutions?: Record<string, { startTime?: number; endTime?: number; duration?: number }>;
  timeline?: TimelineItem[]; // New prop for ordered display
}

// Helper to format relative time
const formatRelativeTime = (timestamp: number): string => {
  const diff = Date.now() - timestamp;
  if (diff < 1000) return 'now';
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return formatTimeOnly(timestamp);
};

// Sequence number formatter (circled numbers)
const formatSequenceNumber = (num: number): string => {
  const circledNumbers = [
    '①',
    '②',
    '③',
    '④',
    '⑤',
    '⑥',
    '⑦',
    '⑧',
    '⑨',
    '⑩',
    '⑪',
    '⑫',
    '⑬',
    '⑭',
    '⑮',
    '⑯',
    '⑰',
    '⑱',
    '⑲',
    '⑳',
  ];
  return num <= 20 ? circledNumbers[num - 1] : `${num}.`;
};

// TimelineNode component for individual items
interface TimelineNodeProps {
  type: 'thought' | 'tool_call';
  sequence: number;
  timestamp: number;
  children: React.ReactNode;
  isLast: boolean;
}

// Memoize TimelineNode to prevent re-renders when parent re-renders
const TimelineNode: React.FC<TimelineNodeProps> = memo(
  ({ type, sequence, timestamp, children, isLast }) => {
    const isThought = type === 'thought';

    return (
      <div className="relative pl-8 pb-4">
        {/* Connecting line */}
        {!isLast && <div className="absolute left-[7px] top-5 bottom-0 w-0.5 bg-slate-200" />}

        {/* Status dot */}
        <div
          className={`absolute left-0 top-1 w-4 h-4 rounded-full border-2 flex items-center justify-center ${
            isThought ? 'bg-amber-100 border-amber-400' : 'bg-blue-100 border-blue-400'
          }`}
        >
          <div
            className={`w-1.5 h-1.5 rounded-full ${isThought ? 'bg-amber-500' : 'bg-blue-500'}`}
          />
        </div>

        {/* Timeline content */}
        <div
          className={`rounded-lg p-3 ${
            isThought
              ? 'bg-amber-50/50 border border-amber-100'
              : 'bg-blue-50/30 border border-blue-100'
          }`}
        >
          {/* Header with icon, sequence, and timestamp */}
          <div className="flex items-center gap-2 mb-1">
            {isThought ? (
              <BulbOutlined className="text-amber-500 text-sm" />
            ) : (
              <ToolOutlined className="text-blue-500 text-sm" />
            )}
            <span className="text-xs font-semibold text-slate-600">
              {formatSequenceNumber(sequence)} {isThought ? 'Thought' : 'Tool Call'}
            </span>
            <span className="ml-auto text-xs text-slate-400">{formatRelativeTime(timestamp)}</span>
          </div>

          {/* Content */}
          <div className={isThought ? 'text-slate-600 text-sm italic' : ''}>{children}</div>
        </div>
      </div>
    );
  }
);

TimelineNode.displayName = 'TimelineNode';

export const ThinkingChain: React.FC<ThinkingChainProps> = memo(
  ({
    thoughts,
    toolCalls = [],
    toolResults = [],
    isThinking = false,
    toolExecutions = {},
    timeline = [],
  }) => {
    // If no timeline provided, fallback to old grouped rendering (or synthesize one)
    // But store now provides timeline, so we prefer that.

    const hasContent = timeline.length > 0 || thoughts.length > 0 || toolCalls.length > 0;

    // Memoize header to avoid re-creation on every render
    // Must be before any early returns to follow rules of hooks
    const header = useMemo(
      () => (
        <div className="flex items-center gap-2 text-slate-500">
          <BulbOutlined className={isThinking ? 'animate-pulse text-amber-500' : ''} />
          <span className="text-xs font-medium">
            {isThinking ? 'Thinking...' : 'Thought Process'}
          </span>
        </div>
      ),
      [isThinking]
    );

    // Memoize timeline items to avoid re-creation on every render
    // Must be before any early returns to follow rules of hooks
    const timelineItems = useMemo(() => {
      const items: React.ReactNode[] = [];

      if (timeline.length > 0) {
        timeline.forEach((item, index) => {
          const isLast = index === timeline.length - 1;
          const sequence = index + 1;

          if (item.type === 'thought') {
            items.push(
              <TimelineNode
                key={item.id}
                type="thought"
                sequence={sequence}
                timestamp={item.timestamp}
                isLast={isLast}
              >
                <span className="break-words">{item.content}</span>
              </TimelineNode>
            );
          } else if (item.type === 'tool_call') {
            const result = toolResults.find((r) => r.tool_name === item.toolName);
            const status = result ? (result.error ? 'failed' : 'success') : 'running';
            const execution = toolExecutions[item.toolName!];

            items.push(
              <TimelineNode
                key={item.id}
                type="tool_call"
                sequence={sequence}
                timestamp={item.timestamp}
                isLast={isLast}
              >
                <ToolCard
                  toolName={item.toolName!}
                  input={item.toolInput}
                  result={result?.result || result?.error}
                  status={status}
                  startTime={execution?.startTime}
                  endTime={execution?.endTime}
                  duration={execution?.duration}
                  embedded={true}
                />
              </TimelineNode>
            );
          }
        });
      } else {
        // Fallback: Render thoughts then tools (with synthesized timeline)
        const fallbackItems: Array<{
          type: 'thought' | 'tool_call';
          content?: string;
          toolName?: string;
          toolInput?: any;
          timestamp: number;
        }> = [];

        // Add thoughts first
        // Use 0 as timestamp for fallback items (they're just placeholders, not real data)
        thoughts.forEach((thought) => {
          fallbackItems.push({ type: 'thought', content: thought, timestamp: 0 });
        });

        // Then add tools
        toolCalls.forEach((call) => {
          fallbackItems.push({
            type: 'tool_call',
            toolName: call.name,
            toolInput: call.arguments,
            timestamp: 0,
          });
        });

        fallbackItems.forEach((item, index) => {
          const isLast = index === fallbackItems.length - 1;
          const sequence = index + 1;

          if (item.type === 'thought') {
            items.push(
              <TimelineNode
                key={`fallback-thought-${index}`}
                type="thought"
                sequence={sequence}
                timestamp={item.timestamp}
                isLast={isLast}
              >
                <span className="break-words">{item.content}</span>
              </TimelineNode>
            );
          } else {
            const result = toolResults.find((r) => r.tool_name === item.toolName);
            const status = result ? (result.error ? 'failed' : 'success') : 'running';
            const execution = toolExecutions[item.toolName!];

            items.push(
              <TimelineNode
                key={`fallback-tool-${index}`}
                type="tool_call"
                sequence={sequence}
                timestamp={item.timestamp}
                isLast={isLast}
              >
                <ToolCard
                  toolName={item.toolName!}
                  input={item.toolInput}
                  result={result?.result || result?.error}
                  status={status}
                  startTime={execution?.startTime}
                  endTime={execution?.endTime}
                  duration={execution?.duration}
                  embedded={true}
                />
              </TimelineNode>
            );
          }
        });
      }

      return items;
    }, [timeline, thoughts, toolCalls, toolResults, toolExecutions]);

    // Early return after all hooks
    if (!hasContent && !isThinking) return null;

    return (
      <Collapse
        ghost
        size="small"
        className="mb-4 bg-slate-50/50 rounded-lg border border-slate-100 w-full max-w-full"
        items={[
          {
            key: '1',
            label: header,
            children: <div className="py-2 max-w-full overflow-hidden">{timelineItems}</div>,
            className: 'max-w-full',
          },
        ]}
      />
    );
  }
);

ThinkingChain.displayName = 'ThinkingChain';

export default ThinkingChain;
