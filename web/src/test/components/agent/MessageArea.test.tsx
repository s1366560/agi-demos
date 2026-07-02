/**
 * Tests for MessageArea Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useStreamingStore } from '../../../stores/agent/streamingStore';

import { MessageArea } from '../../../components/agent/MessageArea';

const virtualizerMock = vi.hoisted(() => ({
  measureElement: vi.fn(),
  measure: vi.fn(),
  scrollToIndex: vi.fn(),
  options: [] as Array<{
    count: number;
    getItemKey?: ((index: number) => string | number) | undefined;
  }>,
}));

// Mock virtualizer to render all rows in tests
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: (options: {
    count: number;
    getItemKey?: ((index: number) => string | number) | undefined;
  }) => {
    virtualizerMock.options.push(options);
    return {
      getTotalSize: () => options.count * 80,
      getVirtualItems: () =>
        Array.from({ length: options.count }, (_, index) => ({
          index,
          start: index * 80,
          size: 80,
          key: options.getItemKey?.(index) ?? index,
        })),
      measureElement: virtualizerMock.measureElement,
      scrollToIndex: virtualizerMock.scrollToIndex,
      measure: virtualizerMock.measure,
    };
  },
}));

// Mock the dependencies
vi.mock('../../../components/agent/MessageBubble', () => ({
  MessageBubble: ({ event, isStreaming }: any) => (
    <div data-testid={`message-${event.id || 'unknown'}`} data-streaming={isStreaming}>
      {event.content || 'Test message'}
    </div>
  ),
}));

vi.mock('../../../components/agent/chat/ThinkingBlock', () => ({
  ThinkingBlock: ({ content, isStreaming }: any) => (
    <div data-testid="streaming-thought" data-streaming={isStreaming}>
      {content || 'Thinking...'}
    </div>
  ),
}));

vi.mock('react-markdown', () => ({
  default: ({ children, _remarkPlugins }: any) => <div data-testid="markdown">{children}</div>,
}));

vi.mock('remark-gfm', () => ({
  default: () => ({}),
}));

// Mock timeline data
const mockTimeline: any[] = [
  { id: '1', type: 'user_message', content: 'Hello', timestamp: 1 },
  { id: '2', type: 'assistant_message', content: 'Hi there!', timestamp: 2 },
];

function defineScrollMetrics(
  element: HTMLElement,
  metrics: { scrollHeight: number; clientHeight: number }
) {
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    get: () => metrics.scrollHeight,
  });
  Object.defineProperty(element, 'clientHeight', {
    configurable: true,
    get: () => metrics.clientHeight,
  });
}

describe('MessageArea Compound Component', () => {
  const defaultProps = {
    timeline: mockTimeline,
    isStreaming: false,
    isLoading: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    virtualizerMock.options.length = 0;
    useStreamingStore.setState({
      agentStreamingAssistantContent: '',
      agentStreamingThought: '',
      agentIsThinkingStreaming: false,
    });
  });

  describe('Root Component', () => {
    it('should render with timeline', () => {
      render(<MessageArea {...defaultProps} />);

      expect(screen.getByTestId('message-1')).toBeInTheDocument();
      expect(screen.getByTestId('message-2')).toBeInTheDocument();
    });

    it('should render with streaming content', () => {
      useStreamingStore.setState({ agentStreamingAssistantContent: 'Streaming...' });
      render(<MessageArea {...defaultProps} isStreaming />);

      expect(screen.getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('Streaming...')).toBeInTheDocument();
    });

    it('should support custom preloadItemCount', () => {
      render(<MessageArea {...defaultProps} preloadItemCount={20} />);

      expect(screen.getByTestId('message-1')).toBeInTheDocument();
    });

    it('should remeasure virtual rows when rendered content resizes', () => {
      const resizeCallbacks: ResizeObserverCallback[] = [];
      const originalResizeObserver = globalThis.ResizeObserver;
      const observeSpy = vi.fn();
      const requestAnimationFrameSpy = vi
        .spyOn(window, 'requestAnimationFrame')
        .mockImplementation((callback: FrameRequestCallback) => {
          callback(0);
          return 1;
        });

      class MockResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resizeCallbacks.push(callback);
        }

        observe = observeSpy;
        unobserve = vi.fn();
        disconnect = vi.fn();
      }

      globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;

      try {
        render(<MessageArea {...defaultProps} />);

        const row = document.querySelector('[data-index="0"]');
        expect(row).toBeInstanceOf(HTMLElement);
        expect(resizeCallbacks.length).toBeGreaterThan(0);

        virtualizerMock.measureElement.mockClear();
        resizeCallbacks[0]?.([{ target: row } as ResizeObserverEntry], {} as ResizeObserver);

        expect(virtualizerMock.measureElement).toHaveBeenCalledWith(row);
        expect(observeSpy).toHaveBeenCalledWith(row);
      } finally {
        globalThis.ResizeObserver = originalResizeObserver;
        requestAnimationFrameSpy.mockRestore();
      }
    });

    it('should pass stable content-aware item keys to the virtualizer', () => {
      render(<MessageArea {...defaultProps} />);

      const latestOptions = virtualizerMock.options.at(-1);
      expect(latestOptions?.getItemKey?.(0)).toBe('1');
      expect(latestOptions?.getItemKey?.(1)).toBe('2');
    });

    it('should remeasure when the same index changes into a long timeline group', () => {
      const shortTimeline: any[] = [
        { id: 'user-1', type: 'user_message', content: 'Run diagnostics', timestamp: 1 },
      ];
      const longCommand = `set +e\n${'printf "diagnostics=%s\\n" "$VALUE"\n'.repeat(80)}`;
      const longTimeline: any[] = [
        {
          id: 'act-1',
          type: 'act',
          toolName: 'terminal_command',
          toolInput: { command: longCommand },
          execution_id: 'exec-1',
          timestamp: 2,
        },
        {
          id: 'observe-1',
          type: 'observe',
          toolName: 'terminal_command',
          toolOutput: { output: `${longCommand}\n${longCommand}` },
          execution_id: 'exec-1',
          timestamp: 3,
          isError: false,
        },
      ];

      const { rerender } = render(
        <MessageArea timeline={shortTimeline} isStreaming={false} isLoading={false} />
      );
      virtualizerMock.measure.mockClear();

      rerender(<MessageArea timeline={longTimeline} isStreaming={false} isLoading={false} />);

      expect(virtualizerMock.options.at(-1)?.getItemKey?.(0)).toBe('timeline:0:exec-1');
      expect(virtualizerMock.measure).toHaveBeenCalled();
    });

    it('should keep timeline item identity stable as realtime steps are appended', () => {
      const runningTimeline: any[] = [
        {
          id: 'act-1',
          type: 'act',
          toolName: 'terminal_command',
          toolInput: { command: 'echo first' },
          execution_id: 'exec-1',
          timestamp: 1,
        },
      ];
      const completedTimeline: any[] = [
        ...runningTimeline,
        {
          id: 'observe-1',
          type: 'observe',
          toolName: 'terminal_command',
          toolOutput: { output: 'first' },
          execution_id: 'exec-1',
          timestamp: 2,
          isError: false,
        },
      ];

      const { rerender } = render(
        <MessageArea timeline={runningTimeline} isStreaming isLoading={false} />
      );
      const initialKey = virtualizerMock.options.at(-1)?.getItemKey?.(0);

      rerender(<MessageArea timeline={completedTimeline} isStreaming isLoading={false} />);

      expect(virtualizerMock.options.at(-1)?.getItemKey?.(0)).toBe(initialKey);
      expect(virtualizerMock.measure).toHaveBeenCalled();
    });

    it('should not globally remeasure virtual rows for non-virtual streaming footer updates', () => {
      const { rerender } = render(<MessageArea {...defaultProps} isStreaming />);
      virtualizerMock.measure.mockClear();

      act(() => {
        useStreamingStore.setState({ agentStreamingAssistantContent: 'streaming token batch' });
      });
      rerender(<MessageArea {...defaultProps} isStreaming />);

      expect(screen.getByText('streaming token batch')).toBeInTheDocument();
      expect(virtualizerMock.measure).not.toHaveBeenCalled();
    });

    it('should not jump to bottom when streaming starts after the user scrolled through history', () => {
      const requestAnimationFrameSpy = vi
        .spyOn(window, 'requestAnimationFrame')
        .mockImplementation((callback: FrameRequestCallback) => {
          callback(0);
          return 1;
        });

      try {
        const { rerender } = render(<MessageArea {...defaultProps} />);
        const container = screen.getByTestId('message-container');
        defineScrollMetrics(container, { scrollHeight: 1000, clientHeight: 300 });

        container.scrollTop = 100;
        fireEvent.scroll(container);

        defineScrollMetrics(container, { scrollHeight: 1200, clientHeight: 300 });
        act(() => {
          useStreamingStore.setState({ agentStreamingAssistantContent: 'new streamed token' });
        });
        rerender(<MessageArea {...defaultProps} isStreaming />);

        expect(container.scrollTop).toBe(100);
      } finally {
        requestAnimationFrameSpy.mockRestore();
      }
    });

    it('should keep following the bottom for streaming footer updates when the user is at bottom', () => {
      const requestAnimationFrameSpy = vi
        .spyOn(window, 'requestAnimationFrame')
        .mockImplementation((callback: FrameRequestCallback) => {
          callback(0);
          return 1;
        });

      try {
        render(<MessageArea {...defaultProps} isStreaming />);
        const container = screen.getByTestId('message-container');
        defineScrollMetrics(container, { scrollHeight: 1000, clientHeight: 300 });
        container.scrollTop = 700;
        fireEvent.scroll(container);

        defineScrollMetrics(container, { scrollHeight: 1200, clientHeight: 300 });
        act(() => {
          useStreamingStore.setState({ agentStreamingAssistantContent: 'streaming token batch' });
        });

        expect(container.scrollTop).toBe(1200);
      } finally {
        requestAnimationFrameSpy.mockRestore();
      }
    });

    it('should not force-scroll to bottom when a live event arrives after the user scrolls up', () => {
      const requestAnimationFrameSpy = vi
        .spyOn(window, 'requestAnimationFrame')
        .mockImplementation((callback: FrameRequestCallback) => {
          callback(0);
          return 1;
        });

      try {
        const { rerender } = render(<MessageArea {...defaultProps} isStreaming />);
        const container = screen.getByTestId('message-container');
        defineScrollMetrics(container, { scrollHeight: 1000, clientHeight: 300 });

        container.scrollTop = 100;
        fireEvent.scroll(container);

        defineScrollMetrics(container, { scrollHeight: 1200, clientHeight: 300 });
        rerender(
          <MessageArea
            {...defaultProps}
            timeline={[
              ...mockTimeline,
              { id: '3', type: 'assistant_message', content: 'New live event', timestamp: 3 },
            ]}
            isStreaming
          />
        );

        expect(container.scrollTop).toBe(100);
      } finally {
        requestAnimationFrameSpy.mockRestore();
      }
    });

    it('should keep the user in history after streaming ends and the next live event arrives', () => {
      const requestAnimationFrameSpy = vi
        .spyOn(window, 'requestAnimationFrame')
        .mockImplementation((callback: FrameRequestCallback) => {
          callback(0);
          return 1;
        });

      try {
        const { rerender } = render(<MessageArea {...defaultProps} isStreaming />);
        const container = screen.getByTestId('message-container');
        defineScrollMetrics(container, { scrollHeight: 1000, clientHeight: 300 });

        container.scrollTop = 100;
        fireEvent.scroll(container);

        rerender(<MessageArea {...defaultProps} isStreaming={false} />);

        defineScrollMetrics(container, { scrollHeight: 1200, clientHeight: 300 });
        rerender(
          <MessageArea
            {...defaultProps}
            timeline={[
              ...mockTimeline,
              { id: '3', type: 'assistant_message', content: 'Next live event', timestamp: 3 },
            ]}
            isStreaming
          />
        );

        expect(container.scrollTop).toBe(100);
      } finally {
        requestAnimationFrameSpy.mockRestore();
      }
    });

    it('should keep following the bottom for live events when the user has not scrolled up', () => {
      const requestAnimationFrameSpy = vi
        .spyOn(window, 'requestAnimationFrame')
        .mockImplementation((callback: FrameRequestCallback) => {
          callback(0);
          return 1;
        });

      try {
        const { rerender } = render(<MessageArea {...defaultProps} isStreaming />);
        const container = screen.getByTestId('message-container');
        defineScrollMetrics(container, { scrollHeight: 1000, clientHeight: 300 });
        container.scrollTop = 700;
        fireEvent.scroll(container);

        defineScrollMetrics(container, { scrollHeight: 1200, clientHeight: 300 });
        rerender(
          <MessageArea
            {...defaultProps}
            timeline={[
              ...mockTimeline,
              { id: '3', type: 'assistant_message', content: 'New live event', timestamp: 3 },
            ]}
            isStreaming
          />
        );

        expect(container.scrollTop).toBe(1200);
      } finally {
        requestAnimationFrameSpy.mockRestore();
      }
    });
  });

  describe('Loading Sub-Component', () => {
    it('should render loading state when isLoading is true', () => {
      render(<MessageArea {...defaultProps} isLoading timeline={[]} />);

      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });

    it('should render with custom message', () => {
      render(
        <MessageArea {...defaultProps} isLoading timeline={[]}>
          <MessageArea.Loading message="Custom loading message" />
        </MessageArea>
      );

      expect(screen.getByText('Custom loading message')).toBeInTheDocument();
    });
  });

  describe('Empty Sub-Component', () => {
    it('should render empty state when timeline is empty', () => {
      render(<MessageArea {...defaultProps} timeline={[]} />);

      expect(screen.getByText(/no messages/i)).toBeInTheDocument();
    });

    it('should render with custom title and subtitle', () => {
      render(
        <MessageArea {...defaultProps} timeline={[]}>
          <MessageArea.Empty title="Custom Title" subtitle="Custom Subtitle" />
        </MessageArea>
      );

      expect(screen.getByText('Custom Title')).toBeInTheDocument();
      expect(screen.getByText('Custom Subtitle')).toBeInTheDocument();
    });
  });

  describe('ScrollIndicator Sub-Component', () => {
    it('should render when loading earlier messages', () => {
      render(<MessageArea {...defaultProps} hasEarlierMessages isLoadingEarlier />);

      expect(screen.getByTestId('scroll-indicator')).toBeInTheDocument();
    });

    it('should not render when not loading earlier messages', () => {
      render(<MessageArea {...defaultProps} />);

      expect(screen.queryByTestId('scroll-indicator')).not.toBeInTheDocument();
    });
  });

  describe('ScrollButton Sub-Component', () => {
    it('should render scroll button when user scrolls up', async () => {
      // This would require scroll event simulation
      // For now, just test the component structure
      render(<MessageArea {...defaultProps} />);
    });
  });

  describe('StreamingContent Sub-Component', () => {
    it('should render streaming thought when thinking', () => {
      useStreamingStore.setState({
        agentStreamingThought: 'Thinking...',
        agentIsThinkingStreaming: true,
      });
      render(<MessageArea {...defaultProps} isStreaming />);

      expect(screen.getByTestId('streaming-thought')).toBeInTheDocument();
      expect(screen.getByText('Thinking...')).toBeInTheDocument();
    });

    it('should render streaming content when streaming', () => {
      useStreamingStore.setState({
        agentStreamingAssistantContent: 'Response...',
        agentIsThinkingStreaming: false,
      });
      render(<MessageArea {...defaultProps} isStreaming />);

      expect(screen.getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('Response...')).toBeInTheDocument();
    });
  });

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', () => {
      render(<MessageArea {...defaultProps} />);

      expect(screen.getByTestId('message-1')).toBeInTheDocument();
      expect(screen.getByTestId('message-2')).toBeInTheDocument();
    });
  });

  describe('MessageArea Namespace', () => {
    it('should export all sub-components', () => {
      expect(MessageArea.Root).toBeDefined();
      expect(MessageArea.Provider).toBeDefined();
      expect(MessageArea.Loading).toBeDefined();
      expect(MessageArea.Empty).toBeDefined();
      expect(MessageArea.ScrollIndicator).toBeDefined();
      expect(MessageArea.ScrollButton).toBeDefined();
      expect(MessageArea.Content).toBeDefined();
      expect(MessageArea.StreamingContent).toBeDefined();
    });

    it('should use Root component as alias', () => {
      render(
        <MessageArea.Root {...defaultProps}>
          <MessageArea.Content />
        </MessageArea.Root>
      );

      expect(screen.getByTestId('message-1')).toBeInTheDocument();
    });
  });
});
