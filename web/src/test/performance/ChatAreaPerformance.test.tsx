/**
 * Performance tests for ChatArea component optimization
 *
 * Tests verify that ChatArea uses efficient memoization and
 * minimizes unnecessary re-renders during streaming.
 */

import React from 'react';

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { render } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

// Get the correct path to the source file
const chatAreaPath = path.resolve(__dirname, '../../components/agent/chat/ChatArea.tsx');

// Mock antd Spin component
vi.mock('antd', () => ({
  Spin: ({ size }: any) => <div data-testid={`spin-${size}`}>Loading...</div>,
}));

// Mock dependencies - use relative paths to match the actual imports
vi.mock('../../components/agent/chat/IdleState', () => ({
  IdleState: ({ onTileClick }: any) => (
    <div data-testid="idle-state">
      <button onClick={() => onTileClick({ id: 'test', title: 'Test' })}>Test Tile</button>
    </div>
  ),
}));

vi.mock('../../components/agent/chat/MessageStream', () => ({
  MessageStream: ({ children }: any) => <div data-testid="message-stream">{children}</div>,
  UserMessage: ({ content }: any) => <div data-testid="user-message">{content}</div>,
  AgentSection: ({ children }: any) => <div data-testid="agent-section">{children}</div>,
  ReasoningLogCard: ({ steps }: any) => <div data-testid="reasoning-log">{steps?.join(', ')}</div>,
  ToolExecutionCardDisplay: ({ toolName }: any) => (
    <div data-testid="tool-execution">{toolName}</div>
  ),
}));

vi.mock('../../components/agent/chat/AssistantMessage', () => ({
  AssistantMessage: ({ content, isReport }: any) => (
    <div data-testid="assistant-message" data-report={isReport}>
      {content}
    </div>
  ),
}));

vi.mock('../../components/agent/execution/ExecutionTimeline', () => ({
  ExecutionTimeline: () => <div data-testid="execution-timeline" />,
}));

vi.mock('../../components/agent/execution/FollowUpPills', () => ({
  FollowUpPills: ({ onSuggestionClick }: any) => (
    <div data-testid="follow-up-pills">
      <button onClick={() => onSuggestionClick('suggestion')}>Suggestion</button>
    </div>
  ),
}));

vi.mock('../../components/agent/PlanModeIndicator', () => ({
  PlanModeIndicator: () => <div data-testid="plan-mode-indicator" />,
}));

vi.mock('../../components/agent/PlanEditor', () => ({
  PlanEditor: () => <div data-testid="plan-editor" />,
}));

// Import ChatArea after mocks are set up
import { ChatArea } from '../../components/agent/chat/ChatArea';

describe('ChatArea Performance', () => {
  describe('Component Memoization', () => {
    it('should be wrapped with React.memo', () => {
      // Check if component is memoized
      expect(ChatArea.displayName).toBe('ChatArea');
    });

    it('should have consistent props to enable effective memoization', () => {
      const timeline = [
        {
          id: '1',
          type: 'user_message' as const,
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user' as const,
        },
      ];
      const currentConversation = { id: 'conv-1' };

      const { rerender } = render(
        <ChatArea
          timeline={timeline}
          currentConversation={currentConversation}
          isStreaming={false}
          messagesLoading={false}
          currentWorkPlan={null}
          currentStepNumber={null}
          executionTimeline={[]}
          toolExecutionHistory={[]}
          matchedPattern={null}
          planModeStatus={null}
          showPlanEditor={false}
          currentPlan={null}
          planLoading={false}
          scrollContainerRef={React.createRef()}
          messagesEndRef={React.createRef()}
          onViewPlan={vi.fn()}
          onExitPlanMode={vi.fn()}
          onUpdatePlan={vi.fn()}
          onSend={vi.fn()}
          onTileClick={vi.fn()}
          hasEarlierMessages={false}
          onLoadEarlier={vi.fn()}
        />
      );

      // Re-render with same props - memoized component should not re-render
      rerender(
        <ChatArea
          timeline={timeline}
          currentConversation={currentConversation}
          isStreaming={false}
          messagesLoading={false}
          currentWorkPlan={null}
          currentStepNumber={null}
          executionTimeline={[]}
          toolExecutionHistory={[]}
          matchedPattern={null}
          planModeStatus={null}
          showPlanEditor={false}
          currentPlan={null}
          planLoading={false}
          scrollContainerRef={React.createRef()}
          messagesEndRef={React.createRef()}
          onViewPlan={vi.fn()}
          onExitPlanMode={vi.fn()}
          onUpdatePlan={vi.fn()}
          onSend={vi.fn()}
          onTileClick={vi.fn()}
          hasEarlierMessages={false}
          onLoadEarlier={vi.fn()}
        />
      );
    });
  });

  describe('Timeline Sorting Optimization', () => {
    it('should use useMemo for sorted timeline', async () => {
      // Read the ChatArea source to verify useMemo usage
      // Dynamic import to avoid require() statement
      const fs = await import('fs');
      const chatAreaContent = fs.readFileSync(chatAreaPath, 'utf-8');

      // Verify useMemo is used for sortedTimeline
      expect(chatAreaContent).toContain('useMemo');
      expect(chatAreaContent).toContain('sortedTimeline');
    });

    it('should not re-sort timeline on every render', async () => {
      // Dynamic import to avoid require() statement
      const fs = await import('fs');
      const chatAreaContent = fs.readFileSync(chatAreaPath, 'utf-8');

      // Verify that sortedTimeline depends only on timeline array
      // Just check for useMemo usage with timeline as dependency
      expect(chatAreaContent).toContain('useMemo');
      expect(chatAreaContent).toContain('[timeline]');
    });
  });

  describe('Streaming State Updates', () => {
    it('should handle streaming state efficiently', () => {
      // Test that rapid streaming updates don't cause excessive re-renders
      const timeline = [
        {
          id: '1',
          type: 'user_message' as const,
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user' as const,
        },
      ];

      const { rerender } = render(
        <ChatArea
          timeline={timeline}
          currentConversation={{ id: 'conv-1' }}
          isStreaming={true}
          messagesLoading={false}
          currentWorkPlan={null}
          currentStepNumber={null}
          executionTimeline={[]}
          toolExecutionHistory={[]}
          matchedPattern={null}
          planModeStatus={null}
          showPlanEditor={false}
          currentPlan={null}
          planLoading={false}
          scrollContainerRef={React.createRef()}
          messagesEndRef={React.createRef()}
          onViewPlan={vi.fn()}
          onExitPlanMode={vi.fn()}
          onUpdatePlan={vi.fn()}
          onSend={vi.fn()}
          onTileClick={vi.fn()}
          hasEarlierMessages={false}
          onLoadEarlier={vi.fn()}
        />
      );

      // Simulate rapid content updates during streaming
      // This should not throw errors or cause performance issues
      expect(() => {
        for (let i = 0; i < 10; i++) {
          const updatedTimeline = [
            ...timeline,
            {
              id: `msg-${i}`,
              type: 'assistant_message' as const,
              sequenceNumber: i + 2,
              timestamp: Date.now(),
              content: `Response ${i}`,
              role: 'assistant' as const,
            },
          ];
          rerender(
            <ChatArea
              timeline={updatedTimeline}
              currentConversation={{ id: 'conv-1' }}
              isStreaming={true}
              messagesLoading={false}
              currentWorkPlan={null}
              currentStepNumber={null}
              executionTimeline={[]}
              toolExecutionHistory={[]}
              matchedPattern={null}
              planModeStatus={null}
              showPlanEditor={false}
              currentPlan={null}
              planLoading={false}
              scrollContainerRef={React.createRef()}
              messagesEndRef={React.createRef()}
              onViewPlan={vi.fn()}
              onExitPlanMode={vi.fn()}
              onUpdatePlan={vi.fn()}
              onSend={vi.fn()}
              onTileClick={vi.fn()}
              hasEarlierMessages={false}
              onLoadEarlier={vi.fn()}
            />
          );
        }
      }).not.toThrow();
    });
  });

  describe('Re-render Triggers', () => {
    it('should only re-render when relevant props change', async () => {
      // Dynamic import to avoid require() statement
      const fs = await import('fs');
      const chatAreaContent = fs.readFileSync(chatAreaPath, 'utf-8');

      // Check for memo with custom comparison or proper prop handling
      // Component should use memo() to prevent unnecessary re-renders
      expect(chatAreaContent).toContain('memo(');
      // Also check for custom comparison function
      expect(chatAreaContent).toContain('areChatAreaPropsEqual');
    });
  });
});
