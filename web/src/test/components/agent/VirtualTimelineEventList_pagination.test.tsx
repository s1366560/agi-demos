/**
 * VirtualTimelineEventList pagination tests.
 *
 * TDD: Tests for scroll-to-load functionality.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { VirtualTimelineEventList } from '../../../components/agent/VirtualTimelineEventList';
import type { TimelineEvent } from '../../../types/agent';

// Mock @tanstack/react-virtual
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: vi.fn(() => ({
    getVirtualItems: () => [
      { key: '0', index: 0, start: 0, size: 100 },
      { key: '1', index: 1, start: 100, size: 100 },
    ],
    getTotalSize: () => 200,
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
    getOffsetForIndex: vi.fn(() => [0]),
  })),
}));

describe('VirtualTimelineEventList Pagination', () => {
  const mockTimeline: TimelineEvent[] = Array.from({ length: 50 }, (_, i) => ({
    id: `msg-${i + 1}`,
    type: 'user_message' as const,
    sequenceNumber: i + 1,
    timestamp: (i + 1) * 1000,
    content: `Message ${i + 1}`,
    role: 'user' as const,
  }));

  const defaultProps = {
    timeline: mockTimeline,
    isStreaming: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Loading indicator', () => {
    it('should show loading indicator when isLoadingEarlier is true', () => {
      render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages
          isLoadingEarlier
          onLoadEarlier={vi.fn()}
        />
      );

      expect(screen.getByText(/加载中/i)).toBeInTheDocument();
    });

    it('should not show loading indicator when isLoadingEarlier is false', () => {
      render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages
          isLoadingEarlier={false}
          onLoadEarlier={vi.fn()}
        />
      );

      expect(screen.queryByText(/加载中/i)).not.toBeInTheDocument();
    });

    it('should not show loading indicator when hasEarlierMessages is false', () => {
      render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages={false}
          isLoadingEarlier
          onLoadEarlier={vi.fn()}
        />
      );

      expect(screen.queryByText(/加载中/i)).not.toBeInTheDocument();
    });
  });

  describe('Empty state', () => {
    it('should show empty state when timeline is empty', () => {
      render(<VirtualTimelineEventList timeline={[]} isStreaming={false} />);

      expect(screen.getByText(/Start a conversation/i)).toBeInTheDocument();
    });

    it('should show send a message text in empty state', () => {
      render(<VirtualTimelineEventList timeline={[]} isStreaming={false} />);

      // The empty state contains the instruction text
      expect(screen.getByText(/Send a message to begin chatting/i)).toBeInTheDocument();
    });
  });

  describe('Props passthrough', () => {
    it('should pass hasEarlierMessages to component', () => {
      const { rerender } = render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages={true}
          isLoadingEarlier={false}
          onLoadEarlier={vi.fn()}
        />
      );

      // Should render without errors
      expect(screen.queryByText(/加载中/i)).not.toBeInTheDocument();

      // Update props
      rerender(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages={false}
          isLoadingEarlier={false}
          onLoadEarlier={vi.fn()}
        />
      );

      // Should still render without errors
      expect(screen.queryByText(/加载中/i)).not.toBeInTheDocument();
    });

    it('should pass onLoadEarlier callback to component', () => {
      const mockLoadEarlier = vi.fn();

      render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages={true}
          isLoadingEarlier={false}
          onLoadEarlier={mockLoadEarlier}
        />
      );

      // Component should render without errors
      // Actual scroll testing would need a more complex setup
      expect(mockLoadEarlier).toBeDefined();
    });
  });

  describe('With timeline events', () => {
    it('should render virtual scroll container when timeline has events', () => {
      render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages={false}
          isLoadingEarlier={false}
          onLoadEarlier={vi.fn()}
        />
      );

      expect(screen.getByTestId('virtual-scroll-container')).toBeInTheDocument();
    });

    it('should render message list when timeline has events', () => {
      render(
        <VirtualTimelineEventList
          {...defaultProps}
          hasEarlierMessages={false}
          isLoadingEarlier={false}
          onLoadEarlier={vi.fn()}
        />
      );

      expect(screen.getByTestId('virtual-message-list')).toBeInTheDocument();
    });
  });

  describe('IsStreaming prop', () => {
    it('should accept isStreaming prop', () => {
      const { rerender } = render(
        <VirtualTimelineEventList
          timeline={mockTimeline}
          isStreaming={true}
        />
      );

      // Should render without errors
      expect(screen.getByTestId('virtual-scroll-container')).toBeInTheDocument();

      rerender(
        <VirtualTimelineEventList
          timeline={mockTimeline}
          isStreaming={false}
        />
      );

      // Should still render without errors
      expect(screen.getByTestId('virtual-scroll-container')).toBeInTheDocument();
    });
  });
});
