/**
 * ThoughtBubble component (T053)
 *
 * Displays the agent's thinking process at both
 * work-level and task-level with collapsible sections.
 *
 * PERFORMANCE: Wrapped with React.memo to prevent unnecessary re-renders.
 */

import React, { useState, memo } from "react";
import { Card, Typography, Space, Tag } from "antd";
import {
  BulbOutlined,
  CaretDownOutlined,
  CaretRightOutlined,
} from "@ant-design/icons";
import type { ThoughtLevel } from "../../types/agent";

const { Text } = Typography;

interface ThoughtBubbleProps {
  thought: string;
  level: ThoughtLevel;
  stepNumber?: number;
  stepDescription?: string;
  isThinking?: boolean;
}

const levelConfig: Record<
  ThoughtLevel,
  { color: string; label: string; class: string }
> = {
  work: {
    color: "purple",
    label: "Work-level Thinking",
    class: "thought-work",
  },
  task: { color: "cyan", label: "Task-level Thinking", class: "thought-task" },
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
    return (
      <div
        data-testid="thought-bubble"
        className={`thought-bubble ${config.class}`}
        style={{
          padding: 8,
          marginBottom: 8,
          borderRadius: 4,
          backgroundColor: level === "work" ? "#f9f0ff" : "#e6fffb",
          border: `1px solid ${level === "work" ? "#d3adf7" : "#87e8de"}`,
        }}
        aria-label="Agent thinking process"
      >
        <Space>
          <BulbOutlined />
          <Text type="secondary" italic>
            {isThinking ? "Thinking..." : "Processing..."}
          </Text>
        </Space>
      </div>
    );
  }

  const displayThought =
    collapsed && thought.length > 100
      ? `${thought.substring(0, 100)}...`
      : thought;

  return (
    <Card
      data-testid="thought-bubble"
      size="small"
      className={`thought-bubble ${config.class}`}
      style={{
        marginBottom: 8,
        backgroundColor: level === "work" ? "#f9f0ff" : "#e6fffb",
        border: `1px solid ${level === "work" ? "#d3adf7" : "#87e8de"}`,
      }}
      aria-label="Agent thinking process"
    >
      <Space orientation="vertical" size="small" style={{ width: "100%" }}>
        {/* Header */}
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Space>
            <BulbOutlined
              className={isThinking ? "thinking-animation" : undefined}
              style={{
                animation: isThinking
                  ? "pulse 1.5s ease-in-out infinite"
                  : undefined,
              }}
              data-testid="thinking-indicator"
            />
            <Tag color={config.color} style={{ margin: 0 }}>
              {config.label}
            </Tag>
            {stepNumber !== undefined && (
              <Tag color="default">Step {stepNumber + 1}</Tag>
            )}
          </Space>

          {thought.length > 100 && (
            <Typography.Link
              onClick={() => setCollapsed(!collapsed)}
              style={{ fontSize: 11 }}
              aria-label={collapsed ? "Expand thought" : "Collapse thought"}
            >
              {collapsed ? <CaretRightOutlined /> : <CaretDownOutlined />}
            </Typography.Link>
          )}
        </Space>

        {/* Step Description */}
        {stepDescription && (
          <Text type="secondary" style={{ fontSize: 11 }}>
            {stepDescription}
          </Text>
        )}

        {/* Thought Content */}
        <Text
          italic
          style={{
            display: "block",
            maxHeight: collapsed ? "auto" : "200px",
            overflowY: collapsed ? "visible" : "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {displayThought}
        </Text>
      </Space>
    </Card>
  );
};

export default memo(ThoughtBubble);
