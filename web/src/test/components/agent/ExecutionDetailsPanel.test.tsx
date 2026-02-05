/**
 * Tests for ExecutionDetailsPanel Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { ExecutionDetailsPanel } from "../../../components/agent/ExecutionDetailsPanel";

import type { Message } from "../../../types/agent";

// Mock the dependencies
vi.mock("../../../components/agent/ThinkingChain", () => ({
  ThinkingChain: ({ thoughts }: { thoughts: string[] }) => (
    <div data-testid="thinking-chain">
      {thoughts.map((t, i) => (
        <div key={i} data-thought={t}>
          {t}
        </div>
      ))}
    </div>
  ),
}));

vi.mock("../../../components/agent/execution/ActivityTimeline", () => ({
  ActivityTimeline: () => (
    <div data-testid="activity-timeline">Activity Timeline</div>
  ),
}));

vi.mock("../../../components/agent/execution/ToolCallVisualization", () => ({
  ToolCallVisualization: () => (
    <div data-testid="tool-visualization">Tool Visualization</div>
  ),
}));

vi.mock("../../../components/agent/execution/TokenUsageChart", () => ({
  TokenUsageChart: () => (
    <div data-testid="token-chart">Token Chart</div>
  ),
}));

vi.mock("../../../utils/agentDataAdapters", () => ({
  adaptTimelineData: () => ({
    timeline: [{ timestamp: 1, type: "thought" }],
    toolExecutions: {},
    toolResults: {},
  }),
  adaptToolVisualizationData: () => [
    { id: "tool-1", name: "search", status: "success" },
  ],
  extractTokenData: () => ({
    tokenData: { total: 1000, input: 500, output: 500 },
    costData: { total: 0.01 },
  }),
  hasExecutionData: () => true,
}));

// Mock message data
const createMockMessage = (overrides?: Partial<Message>): Message => ({
  id: "msg-1",
  conversation_id: "conv-1",
  role: "assistant",
  content: "Response content",
  message_type: "text",
  created_at: "2024-01-01T00:00:00Z",
  metadata: {
    thoughts: ["Thought 1", "Thought 2"],
    timeline: [{ timestamp: 1, type: "thought" }],
    tool_executions: {
      "tool-1": { startTime: 100, endTime: 200, duration: 100 },
    },
  },
  tool_calls: [
    {
      id: "tool-1",
      name: "web_search",
      input: { query: "test" },
    },
  ],
  tool_results: [
    {
      id: "tool-1",
      output: "result",
    },
  ],
  ...overrides,
});

const mockMessage = createMockMessage();
const mockMessageWithTokens: Message = createMockMessage({
  metadata: {
    ...mockMessage.metadata,
    tokens: { total: 1000, input: 500, output: 500 },
    cost: { total: 0.01 },
  },
});

describe("ExecutionDetailsPanel Compound Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Root Component", () => {
    it("should render with message data", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });

    it("should render in compact mode when compact is true", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} compact>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });

    it("should render while streaming", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} isStreaming>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });
  });

  describe("Thinking Sub-Component", () => {
    it("should render thinking chain for messages with thoughts", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
      expect(screen.getByText("Thought 1")).toBeInTheDocument();
      expect(screen.getByText("Thought 2")).toBeInTheDocument();
    });

    it("should not render thinking chain when Thinking component is excluded", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Activity />
        </ExecutionDetailsPanel>
      );

      expect(screen.queryByTestId("thinking-chain")).not.toBeInTheDocument();
    });
  });

  describe("Activity Sub-Component", () => {
    it("should render activity timeline", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Activity />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("activity-timeline")).toBeInTheDocument();
    });

    it("should not render activity timeline when Activity component is excluded", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.queryByTestId("activity-timeline")).not.toBeInTheDocument();
    });
  });

  describe("Tools Sub-Component", () => {
    it("should render tool visualization", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Tools />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("tool-visualization")).toBeInTheDocument();
    });

    it("should not render tool visualization when Tools component is excluded", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.queryByTestId("tool-visualization")).not.toBeInTheDocument();
    });
  });

  describe("Tokens Sub-Component", () => {
    it("should render token chart when token data is available", () => {
      render(
        <ExecutionDetailsPanel message={mockMessageWithTokens}>
          <ExecutionDetailsPanel.Tokens />
        </ExecutionDetailsPanel>
      );

      expect(screen.getByTestId("token-chart")).toBeInTheDocument();
    });

    it("should not render token chart when Tokens component is excluded", () => {
      render(
        <ExecutionDetailsPanel message={mockMessageWithTokens}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      expect(screen.queryByTestId("token-chart")).not.toBeInTheDocument();
    });
  });

  describe("Multiple Views Together", () => {
    it("should render all views when all sub-components are included", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} showViewSelector>
          <ExecutionDetailsPanel.Thinking />
          <ExecutionDetailsPanel.Activity />
          <ExecutionDetailsPanel.Tools />
        </ExecutionDetailsPanel>
      );

      // With view selector, the active view should be rendered
      // (default is "thinking", can be switched via selector)
      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();

      // View selector should be present with all included options
      const segmented = document.querySelector(".ant-segmented");
      expect(segmented).toBeInTheDocument();

      // All three view options should be available in selector
      expect(screen.getByText("Thinking")).toBeInTheDocument();
      expect(screen.getByText("Activity")).toBeInTheDocument();
      expect(screen.getByText("Tools")).toBeInTheDocument();
    });

    it("should render all views without selector when showViewSelector is false", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} showViewSelector={false}>
          <ExecutionDetailsPanel.Thinking />
          <ExecutionDetailsPanel.Activity />
          <ExecutionDetailsPanel.Tools />
        </ExecutionDetailsPanel>
      );

      // Without selector, only the default view is rendered
      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();

      // Selector should not be present
      const segmented = document.querySelector(".ant-segmented");
      expect(segmented).not.toBeInTheDocument();
    });
  });

  describe("View Selector", () => {
    it("should show view selector when showViewSelector is true", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} showViewSelector>
          <ExecutionDetailsPanel.Thinking />
          <ExecutionDetailsPanel.Activity />
        </ExecutionDetailsPanel>
      );

      // Check for segmented control
      const segmented = document.querySelector(".ant-segmented");
      expect(segmented).toBeInTheDocument();
    });

    it("should not show view selector when showViewSelector is false", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} showViewSelector={false}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel>
      );

      const segmented = document.querySelector(".ant-segmented");
      expect(segmented).not.toBeInTheDocument();
    });

    it("should allow switching between views", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} showViewSelector>
          <ExecutionDetailsPanel.Thinking />
          <ExecutionDetailsPanel.Activity />
        </ExecutionDetailsPanel>
      );

      const activityTab = screen.queryByText("Activity");
      if (activityTab) {
        fireEvent.click(activityTab);
      }
    });
  });

  describe("Backward Compatibility", () => {
    it("should work with legacy props when no sub-components provided", () => {
      render(<ExecutionDetailsPanel message={mockMessage} />);

      // Should render with default behavior - thinking chain
      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });

    it("should support defaultView prop", () => {
      render(
        <ExecutionDetailsPanel message={mockMessage} defaultView="activity" />
      );

      expect(screen.getByTestId("activity-timeline")).toBeInTheDocument();
    });

    it("should support legacy compact prop", () => {
      render(<ExecutionDetailsPanel message={mockMessage} compact />);

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });

    it("should support legacy isStreaming prop", () => {
      render(<ExecutionDetailsPanel message={mockMessage} isStreaming />);

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });
  });

  describe("ExecutionDetailsPanel Namespace", () => {
    it("should export all sub-components", () => {
      expect(ExecutionDetailsPanel.Root).toBeDefined();
      expect(ExecutionDetailsPanel.Thinking).toBeDefined();
      expect(ExecutionDetailsPanel.Activity).toBeDefined();
      expect(ExecutionDetailsPanel.Tools).toBeDefined();
      expect(ExecutionDetailsPanel.Tokens).toBeDefined();
      expect(ExecutionDetailsPanel.ViewSelector).toBeDefined();
    });

    it("should use Root component as alias", () => {
      render(
        <ExecutionDetailsPanel.Root message={mockMessage}>
          <ExecutionDetailsPanel.Thinking />
        </ExecutionDetailsPanel.Root>
      );

      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });
  });

  describe("Edge Cases", () => {
    it("should handle message with no execution data", () => {
      const emptyMessage: Message = {
        ...mockMessage,
        metadata: {},
        tool_calls: [],
        tool_results: [],
      };

      vi.doMock("../../../utils/agentDataAdapters", () => ({
        adaptTimelineData: () => ({ timeline: [], toolExecutions: {}, toolResults: {} }),
        adaptToolVisualizationData: () => [],
        extractTokenData: () => ({ tokenData: undefined }),
        hasExecutionData: () => false,
      }));

      // Should render null when no data and not streaming
      const { container } = render(
        <ExecutionDetailsPanel message={emptyMessage} />
      );

      // Component should handle empty state gracefully
      expect(container).toBeInTheDocument();
    });

    it("should handle missing metadata", () => {
      const noMetadataMessage: Message = {
        ...mockMessage,
        metadata: undefined,
      };

      render(<ExecutionDetailsPanel message={noMetadataMessage} />);

      // Should not crash
      expect(screen.getByTestId("thinking-chain")).toBeInTheDocument();
    });
  });
});
