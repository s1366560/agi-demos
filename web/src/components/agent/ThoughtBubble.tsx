/**
 * ThoughtBubble component (T053)
 *
 * Displays the agent's thinking process at both
 * work-level and task-level with collapsible sections.
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 */

import React, { useState, memo } from 'react';

import { BulbOutlined, CaretDownOutlined, CaretRightOutlined } from '@ant-design/icons';
import { Card, Typography, Space, Tag } from 'antd';

import type { ThoughtLevel } from '../../types/agent';

const { Text } = Typography;

interface ThoughtBubbleProps {
  thought: string;
  level: ThoughtLevel;
  stepNumber?: number;
  stepDescription?: string;
  isThinking?: boolean;
}

const levelConfig: Record<ThoughtLevel, { color: string; label: string; class: string }> = {
  work: {
    color: 'purple',
    label: 'Work-level Thinking',
    class: 'thought-work',
  },
  task: { color: 'cyan', label: 'Task-level Thinking', class: 'thought-task' },
};

export const ThoughtBubble: React.FC<ThoughtBubbleProps> = ({
  thought,
  level,
  stepNumber,
  stepDescription,
  isThinking = false,
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const config = levelConfig[level];

  // Handle empty thought
  if (!thought) {
    const bgClass = level === 'work' ? 'bg-purple-50' : 'bg-cyan-50';
    const borderClass = level === 'work' ? 'border-purple-300' : 'border-cyan-300';

    return (
      <div
        data-testid="thought-bubble"
        className={`thought-bubble ${config.class} ${bgClass} ${borderClass} border p-2 mb-2 rounded`}
        aria-label="Agent thinking process"
      >
        <Space>
          <BulbOutlined />
          <Text type="secondary" italic>
            {isThinking ? 'Thinking...' : 'Processing...'}
          </Text>
        </Space>
      </div>
    );
  }

  const displayThought =
    collapsed && thought.length > 100 ? `${thought.substring(0, 100)}...` : thought;

  const bgClass = level === 'work' ? 'bg-purple-50' : 'bg-cyan-50';
  const borderClass = level === 'work' ? 'border-purple-300' : 'border-cyan-300';
  const animationClass = isThinking ? 'animate-pulse' : '';
  const maxHeightClass = collapsed ? 'max-h-none' : 'max-h-[200px]';
  const overflowClass = collapsed ? 'overflow-visible' : 'overflow-auto';

  return (
    <Card
      data-testid="thought-bubble"
      size="small"
      className={`thought-bubble ${config.class} ${bgClass} ${borderClass} border mb-2`}
      aria-label="Agent thinking process"
    >
      <Space orientation="vertical" size="small" className="w-full">
        {/* Header */}
        <Space className="w-full justify-between">
          <Space>
            <BulbOutlined className={animationClass} data-testid="thinking-indicator" />
            <Tag color={config.color} className="m-0">
              {config.label}
            </Tag>
            {stepNumber !== undefined ? <Tag color="default">Step {stepNumber + 1}</Tag> : null}
          </Space>

          {thought.length > 100 ? (
            <Typography.Link
              onClick={() => { setCollapsed(!collapsed); }}
              className="text-xs"
              aria-label={collapsed ? 'Expand thought' : 'Collapse thought'}
            >
              {collapsed ? <CaretRightOutlined /> : <CaretDownOutlined />}
            </Typography.Link>
          ) : null}
        </Space>

        {/* Step Description */}
        {stepDescription ? (
          <Text type="secondary" className="text-xs">
            {stepDescription}
          </Text>
        ) : null}

        {/* Thought Content */}
        <Text
          italic
          className={`block ${maxHeightClass} ${overflowClass} whitespace-pre-wrap break-words`}
        >
          {displayThought}
        </Text>
      </Space>
    </Card>
  );
};

export default memo(ThoughtBubble);
