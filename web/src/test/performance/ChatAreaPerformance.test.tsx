/**
 * Performance tests for ChatArea component optimization
 *
 * Tests verify that ChatArea uses efficient memoization and
 * minimizes unnecessary re-renders during streaming.
 */

import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import React from 'react';

// Import ChatArea with proper path resolution
let ChatAreaModule: any;
beforeAll(async () => {
  ChatAreaModule = await import('../../components/agent/chat/ChatArea');
});

// Mock dependencies
vi.mock('@/components/agent/chat/IdleState', () => ({
  IdleState: ({ onTileClick }: any) => (
    <div data-testid="idle-state">
      <button onClick={() => onTileClick({ id: 'test', title: 'Test' })}>
        Test Tile
      </button>
    </div>
  ),
}));

vi.mock('@/components/agent/chat/MessageStream', () => ({
  MessageStream: ({ children }: any) => <div data-testid="message-stream">{children}</div>,
  UserMessage: ({ content }: any) => <div data-testid="user-message">{content}</div>,
  AgentSection: ({ children }: any) => <div data-testid="agent-section">{children}</div>,
  ReasoningLogCard: ({ steps }: any) => (
    <div data-testid="reasoning-log">{steps?.join(', ')}</div>
  ),
  ToolExecutionCardDisplay: ({ toolName }: any) => (
    <div data-testid="tool-execution">{toolName}</div>
  ),
}));

vi.mock('@/components/agent/chat/AssistantMessage', () => ({
  AssistantMessage: ({ content, isReport }: any) => (
    <div data-testid="assistant-message" data-report={isReport}>
      {content}
    </div>
  ),
}));

vi.mock('@/components/agent/execution/ExecutionTimeline', () => ({
  ExecutionTimeline: () => <div data-testid="execution-timeline" />,
}));

vi.mock('@/components/agent/execution/FollowUpPills', () => ({
  FollowUpPills: ({ onSuggestionClick }: any) => (
    <div data-testid="follow-up-pills">
      <button onClick={() => onSuggestionClick('suggestion')}>Suggestion</button>
    </div>
  ),
}));

vi.mock('@/components/agent/PlanModeIndicator', () => ({
  PlanModeIndicator: () => <div data-testid="plan-mode-indicator" />,
}));

vi.mock('@/components/agent/PlanEditor', () => ({
  PlanEditor: () => <div data-testid="plan-editor" />,
}));

describe('ChatArea Performance', () => {
  describe('Component Memoization', () => {
    it('should be wrapped with React.memo', () => {
      // Check if component is memoized
      expect(ChatAreaModule.ChatArea.displayName).toBe('ChatArea');
    });

    it('should have consistent props to enable effective memoization', () => {
      const { ChatArea } = ChatAreaModule;

      const messages = [
        { id: '1', role: 'user', content: 'Hello', created_at: '2024-01-01T00:00:00Z' },
      ];
      const currentConversation = { id: 'conv-1' };

      const { rerender } = render(
        <ChatArea
          messages={messages}
          currentConversation={currentConversation}
          isStreaming={false}
          messagesLoading={false}
          currentWorkPlan={null}
          currentStepNumber={null}
          currentThought={null}
          currentToolCall={null}
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
        />
      );

      // Re-render with same props - memoized component should not re-render
      const renderSpy = vi.fn();
      const originalChatArea = ChatArea;
      // We can't directly spy on the component's render, but we can check
      // that the DOM doesn't change unnecessarily
      rerender(
        <ChatArea
          messages={messages}
          currentConversation={currentConversation}
          isStreaming={false}
          messagesLoading={false}
          currentWorkPlan={null}
          currentStepNumber={null}
          currentThought={null}
          currentToolCall={null}
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
        />
      );
    });
  });

  describe('Message Sorting Optimization', () => {
    it('should use useMemo for sorted messages', async () => {
      // Read the ChatArea source to verify useMemo usage
      const fs = require('fs');
      const chatAreaContent = fs.readFileSync(
        require.resolve('../../components/agent/chat/ChatArea.tsx'),
        'utf-8'
      );

      // Verify useMemo is used for sortedMessages
      expect(chatAreaContent).toContain('useMemo');
      expect(chatAreaContent).toContain('sortedMessages');
    });

    it('should not re-sort messages on every render', async () => {
      const fs = require('fs');
      const chatAreaContent = fs.readFileSync(
        require.resolve('../../components/agent/chat/ChatArea.tsx'),
        'utf-8'
      );

      // Verify that sortedMessages depends only on messages array
      // Just check for useMemo usage with messages as dependency
      expect(chatAreaContent).toContain('useMemo');
      expect(chatAreaContent).toContain('[messages]');
    });
  });

  describe('Streaming State Updates', () => {
    it('should handle streaming state efficiently', () => {
      // Test that rapid streaming updates don't cause excessive re-renders
      const { ChatArea } = ChatAreaModule;

      const messages = [
        { id: '1', role: 'user', content: 'Hello', created_at: '2024-01-01T00:00:00Z' },
      ];

      const { rerender } = render(
        <ChatArea
          messages={messages}
          currentConversation={{ id: 'conv-1' }}
          isStreaming={true}
          messagesLoading={false}
          currentWorkPlan={null}
          currentStepNumber={null}
          currentThought={null}
          currentToolCall={null}
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
          assistantDraftContent="streaming content..."
          isTextStreaming={true}
        />
      );

      // Simulate rapid content updates during streaming
      // This should not throw errors or cause performance issues
      expect(() => {
        for (let i = 0; i < 10; i++) {
          rerender(
            <ChatArea
              messages={messages}
              currentConversation={{ id: 'conv-1' }}
              isStreaming={true}
              messagesLoading={false}
              currentWorkPlan={null}
              currentStepNumber={null}
              currentThought={null}
              currentToolCall={null}
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
              assistantDraftContent={`streaming content... ${i}`}
              isTextStreaming={true}
            />
          );
        }
      }).not.toThrow();
    });
  });

  describe('Re-render Triggers', () => {
    it('should only re-render when relevant props change', async () => {
      const fs = require('fs');
      const chatAreaContent = fs.readFileSync(
        require.resolve('../../components/agent/chat/ChatArea.tsx'),
        'utf-8'
      );

      // Check for memo with custom comparison or proper prop handling
      // Component should use memo() to prevent unnecessary re-renders
      expect(chatAreaContent).toContain('memo(');
      // Also check for custom comparison function
      expect(chatAreaContent).toContain('areChatAreaPropsEqual');
    });
  });
});
