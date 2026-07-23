import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { JitContextCard } from '../../../../components/agent/timeline/JitContextCard';
import { MemoryCapturedStep } from '../../../../components/agent/timeline/MemoryRecalledStep';

import type {
  MemoryCapturedTimelineEvent,
  MemoryRecalledTimelineEvent,
} from '../../../../types/agent';

function payloadOnlyEvent(payload: unknown): MemoryRecalledTimelineEvent {
  return {
    id: 'memory-recalled-1',
    type: 'memory_recalled',
    eventTimeUs: 1,
    eventCounter: 0,
    timestamp: 1,
    payload,
  } as unknown as MemoryRecalledTimelineEvent;
}

describe('JitContextCard', () => {
  it('renders payload-only memory history returned for desktop replay', () => {
    render(
      <JitContextCard
        conversationId="conversation-1"
        event={payloadOnlyEvent({
          memories: [
            {
              content: 'Cross-client memory evidence',
              score: 0.94,
              source: 'project',
              category: 'procedural',
            },
          ],
          count: 1,
          search_ms: 17,
        })}
      />
    );

    const toggle = screen.getByTestId('jit-context-toggle');
    expect(toggle).toHaveTextContent('1');
    expect(toggle).toHaveTextContent('17ms');

    fireEvent.click(toggle);
    expect(screen.getByText('Cross-client memory evidence')).toBeInTheDocument();
  });

  it('ignores malformed cached memory payloads without crashing', () => {
    const { container } = render(
      <JitContextCard
        conversationId="conversation-1"
        event={payloadOnlyEvent({ memories: { content: 'not-an-array' } })}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('renders payload-only memory capture history', () => {
    const event = {
      id: 'memory-captured-1',
      type: 'memory_captured',
      eventTimeUs: 2,
      eventCounter: 0,
      timestamp: 2,
      payload: {
        captured_count: 2,
        categories: ['procedural', 'preference'],
      },
    } as unknown as MemoryCapturedTimelineEvent;

    render(<MemoryCapturedStep event={event} />);

    expect(screen.getByText(/2/)).toBeInTheDocument();
    expect(screen.getByText('(procedural, preference)')).toBeInTheDocument();
  });
});
