/**
 * Tests for VirtualTimelineEventList component
 *
 * Tests the virtual scrolling timeline event list that combines:
 * - @tanstack/react-virtual for performance
 * - TimelineEventGroup for consistent rendering
 * - groupTimelineEvents for event aggregation
 *
 * @see web/src/components/agent/VirtualTimelineEventList.tsx
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VirtualTimelineEventList } from '../../components/agent/VirtualTimelineEventList';
import type { TimelineEvent } from '../../types/agent';

// Mock @tanstack/react-virtual
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: vi.fn((options) => ({
    getVirtualItems: () => {
      const items = [];
      for (let i = 0; i < options.count; i++) {
        items.push({
          index: i,
          key: `item-${i}`,
          start: i * 100,
          end: (i + 1) * 100,
          size: 100,
        });
      }
      return items;
    },
    getTotalSize: () => options.count * 100,
  })),
}));

describe('VirtualTimelineEventList', () => {
  const mockTimeline: TimelineEvent[] = [
    {
      id: 'user-1',
      type: 'user_message',
      sequenceNumber: 1,
      timestamp: Date.now() - 3000,
      content: 'What is the weather?',
      role: 'user',
    } as TimelineEvent,
    {
      id: 'assistant-1',
      type: 'assistant_message',
      sequenceNumber: 2,
      timestamp: Date.now() - 2000,
      content: 'Let me check the weather for you.',
      role: 'assistant',
    } as TimelineEvent,
    {
      id: 'assistant-2',
      type: 'assistant_message',
      sequenceNumber: 3,
      timestamp: Date.now() - 1000,
      content: 'The weather today is sunny with a high of 75°F.',
      role: 'assistant',
    } as TimelineEvent,
  ];

  describe('Rendering', () => {
    it('should render virtual scroll container', () => {
      render(
        <VirtualTimelineEventList
          timeline={mockTimeline}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('virtual-scroll-container')).toBeInTheDocument();
      expect(screen.getByTestId('virtual-message-list')).toBeInTheDocument();
    });

    it('should show empty state when no events', () => {
      render(
        <VirtualTimelineEventList
          timeline={[]}
          isStreaming={false}
        />
      );

      expect(screen.getByText(/Start a conversation/i)).toBeInTheDocument();
    });
  });

  describe('Virtual Scrolling', () => {
    it('should create virtual rows for each event group', () => {
      render(
        <VirtualTimelineEventList
          timeline={mockTimeline}
          isStreaming={false}
        />
      );

      // Should have virtual rows (one per event group)
      expect(screen.getByTestId('virtual-row-0')).toBeInTheDocument();
    });

    it('should handle large timelines with virtual scrolling', () => {
      const largeTimeline: TimelineEvent[] = Array.from({ length: 100 }, (_, i) => ({
        id: `msg-${i}`,
        type: i % 2 === 0 ? 'user_message' : 'assistant_message',
        sequenceNumber: i,
        timestamp: Date.now() - (100 - i) * 1000,
        content: i % 2 === 0 ? `User message ${i}` : `Assistant message ${i}`,
        role: i % 2 === 0 ? 'user' : 'assistant',
      } as TimelineEvent));

      render(
        <VirtualTimelineEventList
          timeline={largeTimeline}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('virtual-row-0')).toBeInTheDocument();
      expect(screen.getByTestId('virtual-row-99')).toBeInTheDocument();
    });
  });

  describe('Streaming Behavior', () => {
    it('should re-render when timeline changes', () => {
      const { rerender } = render(
        <VirtualTimelineEventList
          timeline={mockTimeline.slice(0, 1)}
          isStreaming={false}
        />
      );

      // Should have 1 virtual row initially
      expect(screen.getByTestId('virtual-row-0')).toBeInTheDocument();
      expect(screen.queryByTestId('virtual-row-1')).not.toBeInTheDocument();

      // Add more events
      rerender(
        <VirtualTimelineEventList
          timeline={mockTimeline}
          isStreaming={false}
        />
      );

      // Should have more virtual rows
      expect(screen.getByTestId('virtual-row-2')).toBeInTheDocument();
    });
  });
});

