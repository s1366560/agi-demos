/**
 * ChatArea.test.tsx
 *
 * Tests for the ChatArea component.
 * Tests the VirtualTimelineEventList integration with timeline-only mode.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ChatArea } from '../../../../components/agent/chat/ChatArea';

import type { StarterTile } from '../../../../components/agent/chat/IdleState';
import type { TimelineEvent, WorkPlan, ToolExecution, TimelineStep } from '../../../../types/agent';

// Mock the IdleState component
vi.mock('../../../../components/agent/chat/IdleState', () => ({
  IdleState: ({
    greeting,
    onTileClick,
  }: {
    greeting: string;
    onTileClick: (tile: StarterTile) => void;
  }) => (
    <div data-testid="idle-state">
      <span>{greeting}</span>
      <button
        onClick={() =>
          onTileClick({
            id: 'test',
            title: 'Test',
            description: 'Test tile',
            color: 'blue',
            icon: 'test',
          })
        }
      >
        Click Tile
      </button>
    </div>
  ),
}));

// Mock the ExecutionTimeline component
vi.mock('../../../../components/agent/execution/ExecutionTimeline', () => ({
  ExecutionTimeline: () => <div data-testid="execution-timeline" />,
}));

// Mock the FollowUpPills component
vi.mock('../../../../components/agent/execution/FollowUpPills', () => ({
  FollowUpPills: ({
    suggestions,
    onSuggestionClick,
  }: {
    suggestions: string[];
    onSuggestionClick: (s: string) => void;
  }) => (
    <div data-testid="follow-up-pills">
      {suggestions.map((s) => (
        <button key={s} onClick={() => onSuggestionClick(s)}>
          {s}
        </button>
      ))}
    </div>
  ),
}));

// Mock the VirtualTimelineEventList component
vi.mock('../../../../components/agent/VirtualTimelineEventList', () => ({
  VirtualTimelineEventList: ({
    timeline,
    isStreaming,
    hasEarlierMessages,
    isLoadingEarlier,
    onLoadEarlier,
  }: {
    timeline: TimelineEvent[];
    isStreaming: boolean;
    hasEarlierMessages?: boolean;
    isLoadingEarlier?: boolean;
    onLoadEarlier?: () => void;
  }) => (
    <div data-testid="virtual-timeline-list" data-streaming={isStreaming}>
      Virtual Timeline ({timeline.length} events)
      {hasEarlierMessages && <span data-testid="has-earlier">Has earlier</span>}
      {isLoadingEarlier && <span data-testid="loading-earlier">Loading earlier</span>}
    </div>
  ),
}));

describe('ChatArea', () => {
  const mockScrollContainerRef = { current: null };
  const mockMessagesEndRef = { current: null };

  const defaultProps = {
    timeline: [] as TimelineEvent[],
    currentConversation: null,
    isStreaming: false,
    messagesLoading: false,
    currentWorkPlan: null,
    currentStepNumber: null,
    executionTimeline: [] as TimelineStep[],
    toolExecutionHistory: [] as ToolExecution[],
    matchedPattern: null,
    planModeStatus: null,
    showPlanEditor: false,
    currentPlan: null,
    planLoading: false,
    scrollContainerRef: mockScrollContainerRef,
    messagesEndRef: mockMessagesEndRef,
    onViewPlan: vi.fn(),
    onExitPlanMode: vi.fn(),
    onUpdatePlan: vi.fn(),
    onSend: vi.fn(),
    onTileClick: vi.fn(),
    hasEarlierMessages: false,
    onLoadEarlier: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('With timeline events', () => {
    it('should render messages when timeline has events', () => {
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
        {
          id: '2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'Hi there!',
          role: 'assistant',
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
        />
      );

      // Should show the virtual timeline list (mocked)
      expect(screen.getByTestId('virtual-timeline-list')).toBeInTheDocument();
    });

    it('should render idle state when no conversation', () => {
      render(<ChatArea {...defaultProps} />);

      expect(screen.getByTestId('idle-state')).toBeInTheDocument();
      expect(screen.getByText(/How can I help you today?/)).toBeInTheDocument();
    });

    it('should render idle state when conversation exists but no events', () => {
      render(
        <ChatArea
          {...defaultProps}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          timeline={[]}
        />
      );

      expect(screen.getByTestId('idle-state')).toBeInTheDocument();
    });

    it('should show ExecutionTimeline when streaming with work plan', () => {
      const mockWorkPlan: WorkPlan = {
        id: 'plan-1',
        conversation_id: 'conv-1',
        status: 'in_progress',
        steps: [
          {
            step_number: 1,
            description: 'Step 1',
            expected_output: 'Output 1',
            thought_prompt: '',
            required_tools: [],
            dependencies: [],
          },
          {
            step_number: 2,
            description: 'Step 2',
            expected_output: 'Output 2',
            thought_prompt: '',
            required_tools: [],
            dependencies: [],
          },
        ],
        current_step_index: 0,
        created_at: new Date().toISOString(),
      };

      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          currentWorkPlan={mockWorkPlan}
          isStreaming={true}
        />
      );

      expect(screen.getByTestId('execution-timeline')).toBeInTheDocument();
    });

    it('should show follow-up pills when not streaming and has events', () => {
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
        {
          id: '2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'Hi there!',
          role: 'assistant',
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('follow-up-pills')).toBeInTheDocument();
    });
  });

  describe('User Interactions', () => {
    it('should call onTileClick when starter tile is clicked', () => {
      render(<ChatArea {...defaultProps} />);

      const tileButton = screen.getByText('Click Tile');
      fireEvent.click(tileButton);

      expect(defaultProps.onTileClick).toHaveBeenCalledTimes(1);
    });

    it('should call onSend when follow-up suggestion is clicked', () => {
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
        {
          id: '2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'Hi there!',
          role: 'assistant',
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
        />
      );

      const suggestionButton = screen.getByText('Compare with competitors?');
      fireEvent.click(suggestionButton);

      expect(defaultProps.onSend).toHaveBeenCalledWith('Compare with competitors?');
    });
  });

  describe('Loading States', () => {
    it('should show loading indicator when loading earlier messages', () => {
      render(
        <ChatArea
          {...defaultProps}
          messagesLoading={true}
          hasEarlierMessages={true}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          timeline={[
            {
              id: '1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Hello',
              role: 'user',
            },
          ]}
        />
      );

      expect(screen.getByText(/加载中/)).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('should have proper container structure', () => {
      render(
        <ChatArea
          {...defaultProps}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          timeline={[
            {
              id: '1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Hello',
              role: 'user',
            },
          ]}
        />
      );

      // Check that main container has flex layout
      const mainContainer = document.querySelector('.flex.flex-1.flex-col');
      expect(mainContainer).toBeInTheDocument();

      // Check that virtual timeline list is rendered
      expect(screen.getByTestId('virtual-timeline-list')).toBeInTheDocument();
    });
  });

  describe('Timeline-only Mode', () => {
    it('should render VirtualTimelineEventList with timeline events', () => {
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
        />
      );

      const virtualList = screen.getByTestId('virtual-timeline-list');
      expect(virtualList).toBeInTheDocument();
      expect(virtualList).toHaveTextContent('Virtual Timeline (1 events)');
    });

    it('should pass isStreaming prop to VirtualTimelineEventList', () => {
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          isStreaming={true}
        />
      );

      const virtualList = screen.getByTestId('virtual-timeline-list');
      expect(virtualList).toHaveAttribute('data-streaming', 'true');
    });
  });
});
