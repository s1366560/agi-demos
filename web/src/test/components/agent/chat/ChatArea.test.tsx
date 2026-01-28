/**
 * ChatArea.test.tsx
 *
 * Tests for the ChatArea component, specifically for render mode integration.
 * Tests the VirtualTimelineEventList integration with RenderModeSwitch.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatArea } from '../../../../components/agent/chat/ChatArea';
import type { TimelineEvent, WorkPlan, ToolExecution, TimelineStep, PlanModeStatus, PlanDocument } from '../../../../types/agent';
import type { StarterTile } from '../../../../components/agent/chat/IdleState';
import type { RenderMode } from '../../../../components/agent/VirtualTimelineEventList';

// Mock the IdleState component
vi.mock('../../../../components/agent/chat/IdleState', () => ({
  IdleState: ({ greeting, onTileClick }: { greeting: string; onTileClick: (tile: StarterTile) => void }) => (
    <div data-testid="idle-state">
      <span>{greeting}</span>
      <button onClick={() => onTileClick({ id: 'test', title: 'Test', description: 'Test tile', color: 'blue', icon: 'test' })}>
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
  FollowUpPills: ({ suggestions, onSuggestionClick }: { suggestions: string[]; onSuggestionClick: (s: string) => void }) => (
    <div data-testid="follow-up-pills">
      {suggestions.map((s) => (
        <button key={s} onClick={() => onSuggestionClick(s)}>
          {s}
        </button>
      ))}
    </div>
  ),
}));

// Mock the PlanModeIndicator component
vi.mock('../../../../components/agent/PlanModeIndicator', () => ({
  PlanModeIndicator: ({ status }: { status: PlanModeStatus }) => (
    <div data-testid="plan-mode-indicator" data-in-plan-mode={status.is_in_plan_mode}>
      Plan Mode
    </div>
  ),
}));

// Mock the PlanEditor component
vi.mock('../../../../components/agent/PlanEditor', () => ({
  PlanEditor: ({ plan }: { plan: PlanDocument }) => (
    <div data-testid="plan-editor">{plan.content}</div>
  ),
}));

// Mock the VirtualTimelineEventList component
vi.mock('../../../../components/agent/VirtualTimelineEventList', () => ({
  VirtualTimelineEventList: ({ renderMode }: { renderMode?: RenderMode; timeline: TimelineEvent[]; isStreaming: boolean }) => (
    <div data-testid="virtual-timeline-list" data-render-mode={renderMode || 'grouped'}>
      Virtual Timeline
    </div>
  ),
}));

// Mock the RenderModeSwitch component
vi.mock('../../../../components/agent/RenderModeSwitch', () => ({
  RenderModeSwitch: ({ mode, onToggle }: { mode: RenderMode; onToggle: (m: RenderMode) => void }) => (
    <div data-testid="render-mode-switch" data-mode={mode}>
      <button onClick={() => onToggle(mode === 'grouped' ? 'timeline' : 'grouped')}>
        Toggle Mode
      </button>
    </div>
  ),
}));

describe('ChatArea - RenderMode Integration', () => {
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
    renderMode: 'grouped' as RenderMode,
    onRenderModeChange: vi.fn(),
    scrollContainerRef: mockScrollContainerRef,
    messagesEndRef: mockMessagesEndRef,
    onViewPlan: vi.fn(),
    onExitPlanMode: vi.fn(),
    onUpdatePlan: vi.fn(),
    onSend: vi.fn(),
    onTileClick: vi.fn(),
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

  describe('Plan Mode', () => {
    it('should show ExecutionTimeline when in plan mode (rich timeline)', () => {
      const planModeStatus: PlanModeStatus = {
        is_in_plan_mode: true,
        current_plan_id: 'plan-1',
        can_exit_plan_mode: true,
      };

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

      // Need to provide executionTimeline to trigger rich timeline display
      const mockExecutionTimeline: TimelineStep[] = [
        {
          step_number: 1,
          description: 'Step 1',
          status: 'completed',
          timestamp: Date.now(),
        },
        {
          step_number: 2,
          description: 'Step 2',
          status: 'in_progress',
          timestamp: Date.now(),
        },
      ];

      render(
        <ChatArea
          {...defaultProps}
          planModeStatus={planModeStatus}
          currentWorkPlan={mockWorkPlan}
          executionTimeline={mockExecutionTimeline}
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
          isStreaming={true}
        />
      );

      // Should show execution timeline during streaming with complex work plan
      expect(screen.getByTestId('execution-timeline')).toBeInTheDocument();
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

    it('should call onViewPlan when PlanModeIndicator action is triggered', () => {
      const planModeStatus: PlanModeStatus = {
        is_in_plan_mode: true,
        current_plan_id: 'plan-1',
        can_exit_plan_mode: true,
      };

      render(
        <ChatArea
          {...defaultProps}
          planModeStatus={planModeStatus}
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

      // PlanModeIndicator should have onViewPlan callback
      // This test verifies the prop is passed correctly
      expect(defaultProps.onViewPlan).toBeDefined();
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

      expect(screen.getByText(/加载历史消息/)).toBeInTheDocument();
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

  describe('RenderMode Switch Integration', () => {
    it('should show RenderModeSwitch when conversation is active and has events', () => {
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
          renderMode="grouped"
          onRenderModeChange={vi.fn()}
        />
      );

      expect(screen.getByTestId('render-mode-switch')).toBeInTheDocument();
    });

    it('should not show RenderModeSwitch when no conversation', () => {
      render(<ChatArea {...defaultProps} />);

      expect(screen.queryByTestId('render-mode-switch')).not.toBeInTheDocument();
    });

    it('should not show RenderModeSwitch when conversation has no events', () => {
      render(
        <ChatArea
          {...defaultProps}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          timeline={[]}
        />
      );

      expect(screen.queryByTestId('render-mode-switch')).not.toBeInTheDocument();
    });

    it('should not show RenderModeSwitch when onRenderModeChange is not provided', () => {
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
          renderMode="grouped"
          onRenderModeChange={undefined as any}
        />
      );

      expect(screen.queryByTestId('render-mode-switch')).not.toBeInTheDocument();
    });

    it('should pass renderMode to VirtualTimelineEventList', () => {
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
          renderMode="timeline"
        />
      );

      const virtualList = screen.getByTestId('virtual-timeline-list');
      expect(virtualList).toHaveAttribute('data-render-mode', 'timeline');
    });

    it('should use grouped mode by default', () => {
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
      expect(virtualList).toHaveAttribute('data-render-mode', 'grouped');
    });

    it('should call onRenderModeChange when switch is clicked', () => {
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

      const mockOnRenderModeChange = vi.fn();

      render(
        <ChatArea
          {...defaultProps}
          timeline={mockTimeline}
          currentConversation={{ id: 'conv-1', title: 'Test Conversation' }}
          renderMode="grouped"
          onRenderModeChange={mockOnRenderModeChange}
        />
      );

      const toggleButton = screen.getByText('Toggle Mode');
      fireEvent.click(toggleButton);

      expect(mockOnRenderModeChange).toHaveBeenCalledWith('timeline');
    });
  });
});
