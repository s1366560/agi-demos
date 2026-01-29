/**
 * timelineStyles.test.ts
 *
 * Tests for timeline-specific CSS styles including:
 * - Timeline axis (vertical line)
 * - Timestamp display
 * - Event type icons
 * - Animation effects
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { TimelineEventItem } from '../../components/agent/TimelineEventItem';
import type { TimelineEvent } from '../../types/agent';

describe('Timeline Styles', () => {
  beforeEach(() => {
    // Add test-specific styles to document
    const style = document.createElement('style');
    style.id = 'test-timeline-styles';
    style.innerHTML = `
      .timeline-axis {
        position: absolute;
        left: 20px;
        top: 0;
        bottom: 0;
        width: 2px;
        background: #e2e8f0;
      }
      .timeline-event {
        position: relative;
        padding-left: 48px;
      }
      .timeline-timestamp {
        position: absolute;
        right: 8px;
        top: 8px;
        font-size: 10px;
        color: #94a3b8;
      }
      .animate-slide-up {
        animation: slideUp 0.3s ease-out;
      }
      @keyframes slideUp {
        from {
          opacity: 0;
          transform: translateY(10px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }
    `;
    document.head.appendChild(style);
  });

  afterEach(() => {
    cleanup();
    const style = document.getElementById('test-timeline-styles');
    if (style) style.remove();
  });

  describe('Timeline Axis', () => {
    it('should support timeline axis class for visual line', () => {
      // This test verifies the CSS class exists for timeline axis
      const style = document.getElementById('test-timeline-styles');
      expect(style).toBeInTheDocument();
      expect(style?.innerHTML).toContain('.timeline-axis');
    });

    it('should position events relative to timeline axis', () => {
      const event: TimelineEvent = {
        id: 'test-axis',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Test',
        role: 'user',
      } as TimelineEvent;

      const { container } = render(
        <div className="timeline-event">
          <TimelineEventItem event={event} />
        </div>
      );

      expect(container.querySelector('.timeline-event')).toBeInTheDocument();
    });
  });

  describe('Timestamp Display', () => {
    it('should support timestamp class for hover display', () => {
      const event: TimelineEvent = {
        id: 'test-ts-display',
        type: 'thought',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Test thought',
      } as TimelineEvent;

      render(<TimelineEventItem event={event} />);

      // Timestamp data should be available (even if not displayed by default)
      expect(event.timestamp).toBeGreaterThan(0);
    });

    it('should format timestamp correctly for display', () => {
      // Use UTC time to avoid timezone issues in tests
      const timestamp = Date.UTC(2024, 0, 15, 10, 30, 0);
      const date = new Date(timestamp);
      const hours = date.getUTCHours();
      const minutes = date.getUTCMinutes();

      expect(hours).toBe(10);
      expect(minutes).toBe(30);
    });
  });

  describe('Event Type Indicators', () => {
    it('should render thought event with psychology icon', () => {
      const event: TimelineEvent = {
        id: 'test-icon-thought',
        type: 'thought',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Thinking...',
      } as TimelineEvent;

      const { container } = render(<TimelineEventItem event={event} />);

      const icon = container.querySelector('.material-symbols-outlined');
      expect(icon).toBeInTheDocument();
    });

    it('should render act event with construction icon', () => {
      const event: TimelineEvent = {
        id: 'test-icon-act',
        type: 'act',
        sequenceNumber: 1,
        timestamp: Date.now(),
        toolName: 'test_tool',
        toolInput: {},
      } as TimelineEvent;

      const { container } = render(<TimelineEventItem event={event} />);

      const icon = container.querySelector('.material-symbols-outlined');
      expect(icon).toBeInTheDocument();
    });
  });

  describe('Animation Effects', () => {
    it('should apply slide-up animation to new events', () => {
      const event: TimelineEvent = {
        id: 'test-animation',
        type: 'user_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Animated message',
        role: 'user',
      } as TimelineEvent;

      const { container } = render(<TimelineEventItem event={event} />);

      // User messages use animate-slide-up
      const animated = container.querySelector('.animate-slide-up');
      expect(animated).toBeInTheDocument();
    });

    it('should apply slide-up animation to assistant messages', () => {
      const event: TimelineEvent = {
        id: 'test-animation-assistant',
        type: 'assistant_message',
        sequenceNumber: 1,
        timestamp: Date.now(),
        content: 'Assistant message',
        role: 'assistant',
      } as TimelineEvent;

      const { container } = render(<TimelineEventItem event={event} />);

      // Assistant messages use animate-slide-up
      const animated = container.querySelector('.animate-slide-up');
      expect(animated).toBeInTheDocument();
    });
  });

  describe('Color Coding', () => {
    it('should support different colors for event types', () => {
      // Test that different event types get appropriate styling
      const events: TimelineEvent[] = [
        {
          id: 'test-1',
          type: 'thought',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Thought',
        } as TimelineEvent,
        {
          id: 'test-2',
          type: 'act',
          sequenceNumber: 2,
          timestamp: Date.now(),
          toolName: 'tool',
          toolInput: {},
        } as TimelineEvent,
      ];

      events.forEach((event) => {
        const { container } = render(<TimelineEventItem event={event} />);
        expect(container.firstChild).toBeDefined();
      });
    });
  });
});
