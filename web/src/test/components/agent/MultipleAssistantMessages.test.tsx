/**
 * Test for multiple assistant messages rendering correctly
 *
 * This test verifies that multiple assistant_message events
 * are rendered as separate bubbles, not merged into one.
 */

import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

import { MessageArea } from '../../../components/agent/MessageArea';

import type { TimelineEvent } from '../../../types/agent';

vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 80,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        start: index * 80,
        size: 80,
        key: index,
      })),
    measureElement: vi.fn(),
    scrollToIndex: vi.fn(),
    measure: vi.fn(),
  }),
}));

vi.mock('../../../components/agent/MessageBubble', () => ({
  MessageBubble: ({ event }: { event: { id?: string; content?: string } }) => (
    <div data-testid={`message-${event.id || 'unknown'}`}>{event.content || 'message'}</div>
  ),
}));

// Mock data: After backend fix, each event has unique id = "{event_type}-{sequence_number}"
const mockTimeline: TimelineEvent[] = [
  {
    id: 'user_message-1',
    type: 'user_message',
    sequenceNumber: 1,
    timestamp: Date.now(),
    content: 'hi',
    role: 'user',
  },
  {
    id: 'assistant_message-203',
    type: 'assistant_message',
    sequenceNumber: 203,
    timestamp: Date.now() + 1000,
    content: 'Hello! I am MemStack Agent',
    role: 'assistant',
  },
  {
    id: 'user_message-204',
    type: 'user_message',
    sequenceNumber: 204,
    timestamp: Date.now() + 2000,
    content: '你有哪些技能',
    role: 'user',
  },
  {
    id: 'assistant_message-725',
    type: 'assistant_message',
    sequenceNumber: 725,
    timestamp: Date.now() + 3000,
    content: '我具备以下技能和工具',
    role: 'assistant',
  },
  {
    id: 'user_message-726',
    type: 'user_message',
    sequenceNumber: 726,
    timestamp: Date.now() + 4000,
    content: '继续生成ppt',
    role: 'user',
  },
  {
    id: 'assistant_message-5832',
    type: 'assistant_message',
    sequenceNumber: 5832,
    timestamp: Date.now() + 5000,
    content: '我来为你创建PPT',
    role: 'assistant',
  },
];

describe('Multiple Assistant Messages Rendering', () => {
  it('should render each assistant_message as a separate bubble', () => {
    render(<MessageArea timeline={mockTimeline} isStreaming={false} isLoading={false} />);

    // Verify each assistant event is rendered as a distinct bubble node
    expect(screen.getByTestId('message-assistant_message-203')).toBeInTheDocument();
    expect(screen.getByTestId('message-assistant_message-725')).toBeInTheDocument();
    expect(screen.getByTestId('message-assistant_message-5832')).toBeInTheDocument();
  });

  it('should have unique event IDs for each assistant_message', () => {
    const assistantEvents = mockTimeline.filter((e) => e.type === 'assistant_message');

    // Each should have a unique ID
    const ids = assistantEvents.map((e) => e.id);
    const uniqueIds = new Set(ids);

    expect(ids.length).toBe(3);
    expect(uniqueIds.size).toBe(3); // All IDs should be unique
  });
});
