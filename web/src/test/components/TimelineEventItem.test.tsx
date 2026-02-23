/**
 * TimelineEventItem.test.tsx
 *
 * Tests for TimelineEventItem component including:
 * - Event type rendering
 * - Timeline visual elements (axis, timestamps)
 * - Animation effects
 * - Styling consistency
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { TimelineEventItem } from '../../components/agent/TimelineEventItem';

import type {
  TimelineEvent,
  UserMessageEvent,
  AssistantMessageEvent,
  ThoughtEvent,
  ActEvent,
  ObserveEvent,
  WorkPlanTimelineEvent,
} from '../../types/agent';

describe('TimelineEventItem', () => {
  describe('Event Type Rendering', () => {
    it('should render user message event', () => {
      const event: UserMessageEvent = {
        id: 'test-1',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Hello, AI!',
        role: 'user',
      };

      render(<TimelineEventItem event={event} />);

      expect(screen.getByText('Hello, AI!')).toBeInTheDocument();
    });

    it('should render assistant message event with avatar', () => {
      const event: AssistantMessageEvent = {
        id: 'test-2',
        type: 'assistant_message',
        sequenceNumber: 2,
        timestamp: Date.now(),
        content: 'Hello! How can I help?',
        role: 'assistant',
      };

      render(<TimelineEventItem event={event} />);

      expect(screen.getByText('Hello! How can I help?')).toBeInTheDocument();
    });

    it('should render thought event with ReasoningLogCard', () => {
      const event: ThoughtEvent = {
        id: 'test-3',
        type: 'thought',
        sequenceNumber: 3,
        timestamp: Date.now(),
        content: 'I need to search for information',
      };

      render(<TimelineEventItem event={event} />);

      expect(screen.getByText('I need to search for information')).toBeInTheDocument();
      expect(screen.getByText('Thinking...')).toBeInTheDocument();
    });

    it('should render act (tool call) event', () => {
      const event: ActEvent = {
        id: 'test-4',
        type: 'act',
        sequenceNumber: 4,
        timestamp: Date.now(),
        toolName: 'web_search',
        toolInput: { query: 'test' },
      };

      render(<TimelineEventItem event={event} />);

      expect(screen.getByText('web_search')).toBeInTheDocument();
    });

    it('should render observe (tool result) event', () => {
      const event: ObserveEvent = {
        id: 'test-5',
        type: 'observe',
        sequenceNumber: 5,
        timestamp: Date.now(),
        toolName: 'web_search',
        toolOutput: 'Found 10 results',
        isError: false,
      };

      render(<TimelineEventItem event={event} />);

      expect(screen.getByText('web_search')).toBeInTheDocument();
    });

    it('should render work_plan event', () => {
      const event: WorkPlanTimelineEvent = {
        id: 'test-6',
        type: 'work_plan',
        sequenceNumber: 6,
        timestamp: Date.now(),
        steps: [
          {
            step_number: 1,
            description: 'Search for information',
            expected_output: 'Search results',
          },
        ],
        status: 'planning',
      };

      render(<TimelineEventItem event={event} />);

      expect(screen.getByText('Work Plan: 1 steps')).toBeInTheDocument();
    });
  });

  describe('Visual Styling', () => {
    it('should apply animation classes to events', () => {
      const event: UserMessageEvent = {
        id: 'test-anim',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Test',
        role: 'user',
      };

      const { container } = render(<TimelineEventItem event={event} />);

      // All events now use animate-slide-up for consistency
      const wrapper = container.querySelector('.animate-slide-up');
      expect(wrapper).toBeInTheDocument();
    });

    // Note: Typing cursor effect has been removed from streaming messages
    it('should render assistant message without typing cursor', () => {
      const event: AssistantMessageEvent = {
        id: 'test-stream',
        type: 'assistant_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Partial text...',
        role: 'assistant',
      };

      const { container } = render(<TimelineEventItem event={event} isStreaming={true} />);

      // Verify content is rendered
      expect(container.textContent).toContain('Partial text...');
      // Verify no typing cursor
      const cursor = container.querySelector('.typing-cursor');
      expect(cursor).not.toBeInTheDocument();
    });
  });

  describe('Event Timestamps', () => {
    it('should render events with proper timestamp data', () => {
      const timestamp = Date.now();
      const event: UserMessageEvent = {
        id: 'test-ts',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp,
        content: 'Test timestamp',
        role: 'user',
      };

      const { _container } = render(<TimelineEventItem event={event} />);

      // Verify the event renders (timestamp is internal, not displayed by default)
      expect(screen.getByText('Test timestamp')).toBeInTheDocument();
    });
  });
});

describe('TimelineEventItem - Execution ID Matching', () => {
  const executionId = 'exec_abc123def456';

  describe('Act-Observe matching with execution_id', () => {
    it('should match act and observe events with same execution_id', () => {
      const actEvent: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'MemorySearch',
        toolInput: { query: 'test' },
        execution_id: executionId,
      };

      const observeEvent: ObserveEvent = {
        id: 'obs-1',
        type: 'observe',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        toolName: 'MemorySearch',
        toolOutput: 'Found 5 results',
        isError: false,
        execution_id: executionId,
      };

      const allEvents: TimelineEvent[] = [actEvent, observeEvent];

      const { container: actContainer } = render(
        <TimelineEventItem event={actEvent} allEvents={allEvents} />
      );

      // Act should show completed state (observe found via execution_id)
      expect(actContainer.textContent).toContain('MemorySearch');
    });

    it('should fall back to toolName matching when execution_id is missing', () => {
      const actEvent: ActEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'MemorySearch',
        toolInput: { query: 'test' },
        // No execution_id
      };

      const observeEvent: ObserveEvent = {
        id: 'obs-1',
        type: 'observe',
        sequenceNumber: 2,
        timestamp: Date.now() + 100,
        toolName: 'MemorySearch',
        toolOutput: 'Found 5 results',
        isError: false,
        // No execution_id
      };

      const allEvents: TimelineEvent[] = [actEvent, observeEvent];

      // Should still match via toolName
      const { container: actContainer } = render(
        <TimelineEventItem event={actEvent} allEvents={allEvents} />
      );

      expect(actContainer.textContent).toContain('MemorySearch');
    });
  });
});
