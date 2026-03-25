/**
 * Tests for MessageArea Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useAgentV3Store } from '../../../stores/agentV3';

import { MessageArea } from '../../../components/agent/MessageArea';

// Mock virtualizer to render all rows in tests
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

describe('MessageArea Compound Component', () => {
  const defaultProps = {
    timeline: mockTimeline,
    isStreaming: false,
    isLoading: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useAgentV3Store.setState({
      streamingAssistantContent: '',
      streamingThought: '',
      isThinkingStreaming: false,
    });
  });

  describe('Root Component', () => {
    it('should render with timeline', () => {
      render(<MessageArea {...defaultProps} />);

      expect(screen.getByTestId('message-1')).toBeInTheDocument();
      expect(screen.getByTestId('message-2')).toBeInTheDocument();
    });

    it('should render with streaming content', () => {
      useAgentV3Store.setState({ streamingAssistantContent: 'Streaming...' });
      render(<MessageArea {...defaultProps} isStreaming />);

      expect(screen.getByTestId('markdown')).toBeInTheDocument();
      expect(screen.getByText('Streaming...')).toBeInTheDocument();
    });

    it('should support custom preloadItemCount', () => {
      render(<MessageArea {...defaultProps} preloadItemCount={20} />);

      expect(screen.getByTestId('message-1')).toBeInTheDocument();
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
      useAgentV3Store.setState({ streamingThought: 'Thinking...', isThinkingStreaming: true });
      render(<MessageArea {...defaultProps} isStreaming />);

      expect(screen.getByTestId('streaming-thought')).toBeInTheDocument();
      expect(screen.getByText('Thinking...')).toBeInTheDocument();
    });

    it('should render streaming content when streaming', () => {
      useAgentV3Store.setState({
        streamingAssistantContent: 'Response...',
        isThinkingStreaming: false,
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
