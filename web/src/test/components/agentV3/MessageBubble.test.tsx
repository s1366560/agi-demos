/**
 * Unit tests for MessageBubble component.
 *
 * TDD Phase 3.1: React.memo optimization verification tests.
 *
 * These tests verify that:
 * 1. Component renders correctly with various props
 * 2. Component behavior is preserved after React.memo addition
 * 3. Component handles edge cases properly
 *
 * Feature: Performance optimization with React.memo
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MessageBubble } from '../../../components/agentV3/MessageBubble';
import type { Message } from '../../../types/agent';

// Mock ExecutionDetailsPanel to avoid complex dependencies
vi.mock('../../../components/agentV3/ExecutionDetailsPanel', () => ({
  ExecutionDetailsPanel: ({ message, isStreaming }: { message: Message; isStreaming?: boolean }) => (
    <div data-testid="execution-details-panel">
      <div data-testid="is-streaming">{isStreaming ? 'true' : 'false'}</div>
      <div data-testid="thoughts-count">{message.metadata?.thoughts?.length || 0}</div>
    </div>
  ),
}));

describe('MessageBubble', () => {
  const createMockMessage = (overrides: Partial<Message> = {}): Message => ({
    id: 'msg-1',
    role: 'assistant',
    content: 'Hello, world!',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  });

  describe('Rendering', () => {
    it('should render user message correctly', () => {
      const userMessage = createMockMessage({ role: 'user', content: 'Test message' });

      render(<MessageBubble message={userMessage} />);

      expect(screen.getByText('You')).toBeInTheDocument();
      expect(screen.getByText('Test message')).toBeInTheDocument();
    });

    it('should render assistant message correctly', () => {
      const assistantMessage = createMockMessage({ role: 'assistant', content: 'Assistant response' });

      render(<MessageBubble message={assistantMessage} />);

      expect(screen.getByText('Agent')).toBeInTheDocument();
      expect(screen.getByText('Assistant response')).toBeInTheDocument();
    });

    it('should render timestamp correctly', () => {
      const message = createMockMessage({ created_at: '2024-01-15T10:30:00Z' });

      render(<MessageBubble message={message} />);

      // Check that timestamp is rendered (format may vary by locale)
      // Just check that some time element is present
      const timeElement = document.querySelector('.text-xs.text-slate-400');
      expect(timeElement).toBeInTheDocument();
    });

    it('should render empty message when streaming and no content', () => {
      const message = createMockMessage({ role: 'assistant', content: '' });

      render(<MessageBubble message={message} isStreaming={true} />);

      // Should show placeholder when streaming with no content
      expect(screen.getByText('...')).toBeInTheDocument();
    });

    it('should show execution details panel for assistant messages', () => {
      const message = createMockMessage({
        role: 'assistant',
        metadata: { thoughts: ['Thought 1', 'Thought 2'] },
      });

      render(<MessageBubble message={message} />);

      expect(screen.getByTestId('execution-details-panel')).toBeInTheDocument();
      expect(screen.getByTestId('thoughts-count')).toHaveTextContent('2');
    });

    it('should not show execution details panel for user messages', () => {
      const userMessage = createMockMessage({
        role: 'user',
        content: 'User message',
      });

      render(<MessageBubble message={userMessage} />);

      expect(screen.queryByTestId('execution-details-panel')).not.toBeInTheDocument();
    });
  });

  describe('Markdown Rendering', () => {
    it('should render inline code correctly', () => {
      const message = createMockMessage({ content: 'Use `console.log()` for debugging' });

      render(<MessageBubble message={message} />);

      expect(screen.getByText('console.log()')).toBeInTheDocument();
    });

    it('should render code blocks correctly', () => {
      const code = '```javascript\nconst x = 1;\n```';
      const message = createMockMessage({ content: code });

      const { container } = render(<MessageBubble message={message} />);

      // Check that code element is present
      const codeElement = container.querySelector('code');
      expect(codeElement).toBeInTheDocument();
    });

    it('should render bold text correctly', () => {
      const message = createMockMessage({ content: 'This is **bold** text' });

      render(<MessageBubble message={message} />);

      expect(screen.getByText('bold')).toBeInTheDocument();
    });

    it('should render links correctly', () => {
      const message = createMockMessage({ content: '[Link](https://example.com)' });

      render(<MessageBubble message={message} />);

      const link = screen.getByText('Link');
      expect(link).toBeInTheDocument();
      expect(link.closest('a')).toHaveAttribute('href', 'https://example.com');
    });

    it('should render lists correctly', () => {
      const message = createMockMessage({ content: '- Item 1\n- Item 2\n- Item 3' });

      render(<MessageBubble message={message} />);

      expect(screen.getByText('Item 1')).toBeInTheDocument();
      expect(screen.getByText('Item 2')).toBeInTheDocument();
      expect(screen.getByText('Item 3')).toBeInTheDocument();
    });
  });

  describe('Streaming Behavior', () => {
    it('should pass isStreaming prop to ExecutionDetailsPanel', () => {
      const message = createMockMessage({
        role: 'assistant',
        content: 'Response',
      });

      render(<MessageBubble message={message} isStreaming={true} />);

      expect(screen.getByTestId('is-streaming')).toHaveTextContent('true');
    });

    it('should not show placeholder for non-streaming empty messages', () => {
      const message = createMockMessage({ role: 'assistant', content: '' });

      render(<MessageBubble message={message} isStreaming={false} />);

      expect(screen.queryByText('...')).not.toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle very long content without crashing', () => {
      const longContent = 'A'.repeat(10000);
      const message = createMockMessage({ content: longContent });

      expect(() => render(<MessageBubble message={message} />)).not.toThrow();
    });

    it('should handle special characters correctly', () => {
      const specialContent = 'Special: <>&"\'\\/`';
      const message = createMockMessage({ content: specialContent });

      render(<MessageBubble message={message} />);

      expect(screen.getByText(/Special:/)).toBeInTheDocument();
    });

    it('should handle multiline code blocks', () => {
      const multilineCode = '```javascript\nconst a = 1;\nconst b = 2;\nreturn a + b;\n```';
      const message = createMockMessage({ content: multilineCode });

      const { container } = render(<MessageBubble message={message} />);

      // Check that code element is present
      const codeElement = container.querySelector('code');
      expect(codeElement).toBeInTheDocument();
      // Check that the content contains the key parts
      expect(codeElement?.textContent).toContain('return');
    });

    it('should handle messages with only whitespace', () => {
      const message = createMockMessage({ content: '   ' });

      render(<MessageBubble message={message} />);

      // Should still render the bubble
      expect(screen.getByText('Agent')).toBeInTheDocument();
    });

    it('should handle null or undefined metadata gracefully', () => {
      const message: Message = {
        id: 'msg-1',
        role: 'assistant',
        content: 'Test',
        created_at: '2024-01-01T00:00:00Z',
        metadata: undefined,
      };

      expect(() => render(<MessageBubble message={message} />)).not.toThrow();
    });
  });

  describe('Styling', () => {
    it('should apply user message styling', () => {
      const userMessage = createMockMessage({ role: 'user', content: 'Test' });

      const { container } = render(<MessageBubble message={userMessage} />);

      // User messages should be right-aligned
      const bubble = container.querySelector('.justify-end');
      expect(bubble).toBeInTheDocument();
    });

    it('should apply assistant message styling', () => {
      const assistantMessage = createMockMessage({ role: 'assistant', content: 'Test' });

      const { container } = render(<MessageBubble message={assistantMessage} />);

      // Assistant messages should be left-aligned
      const bubble = container.querySelector('.justify-start');
      expect(bubble).toBeInTheDocument();
    });

    it('should show different avatars for user and assistant', () => {
      const userMessage = createMockMessage({ role: 'user', content: 'Test' });
      const { container: userContainer } = render(<MessageBubble message={userMessage} />);
      const userAvatar = userContainer.querySelector('.bg-blue-600');
      expect(userAvatar).toBeInTheDocument();

      const assistantMessage = createMockMessage({ role: 'assistant', content: 'Test' });
      const { container: assistantContainer } = render(<MessageBubble message={assistantMessage} />);
      const assistantAvatar = assistantContainer.querySelector('.bg-emerald-600');
      expect(assistantAvatar).toBeInTheDocument();
    });
  });
});
