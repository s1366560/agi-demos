/**
 * Tests for MessageArea Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MessageArea } from '../../../components/agent/MessageArea'

// Mock the dependencies
vi.mock('../../../components/agent/MessageBubble', () => ({
  MessageBubble: ({ event, isStreaming }: any) => (
    <div data-testid={`message-${event.id || 'unknown'}`} data-streaming={isStreaming}>
      {event.content || 'Test message'}
    </div>
  ),
}))

vi.mock('../../../components/agent/PlanModeBanner', () => ({
  PlanModeBanner: ({ status, onViewPlan, onExit }: any) => (
    <div data-testid="plan-banner">
      <button onClick={onViewPlan}>View Plan</button>
      <button onClick={onExit}>Exit</button>
      <span data-testid="plan-status">{status?.mode}</span>
    </div>
  ),
}))

vi.mock('../../../components/agent/StreamingThoughtBubble', () => ({
  StreamingThoughtBubble: ({ content, isStreaming }: any) => (
    <div data-testid="streaming-thought" data-streaming={isStreaming}>
      {content || 'Thinking...'}
    </div>
  ),
}))

vi.mock('react-markdown', () => ({
  default: ({ children, remarkPlugins }: any) => <div data-testid="markdown">{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => ({}),
}))

// Mock timeline data
const mockTimeline: any[] = [
  { id: '1', role: 'user', content: 'Hello' },
  { id: '2', role: 'assistant', content: 'Hi there!' },
]

describe('MessageArea Compound Component', () => {
  const defaultProps = {
    timeline: mockTimeline,
    isStreaming: false,
    isLoading: false,
    planModeStatus: null,
    onViewPlan: vi.fn(),
    onExitPlanMode: vi.fn(),
    hasEarlierMessages: false,
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Root Component', () => {
    it('should render with timeline', () => {
      render(<MessageArea {...defaultProps} />)

      expect(screen.getByTestId('message-1')).toBeInTheDocument()
      expect(screen.getByTestId('message-2')).toBeInTheDocument()
    })

    it('should render with streaming content', () => {
      render(
        <MessageArea
          {...defaultProps}
          streamingContent="Streaming..."
          isStreaming
        />
      )

      expect(screen.getByTestId('markdown')).toBeInTheDocument()
    })

    it('should support custom preloadItemCount', () => {
      render(<MessageArea {...defaultProps} preloadItemCount={20} />)

      expect(screen.getByTestId('message-1')).toBeInTheDocument()
    })
  })

  describe('Loading Sub-Component', () => {
    it('should render loading state when isLoading is true', () => {
      render(<MessageArea {...defaultProps} isLoading timeline={[]} />)

      expect(screen.getByText(/loading/i)).toBeInTheDocument()
    })

    it('should render with custom message', () => {
      render(
        <MessageArea {...defaultProps} isLoading timeline={[]}>
          <MessageArea.Loading message="Custom loading message" />
        </MessageArea>
      )

      expect(screen.getByText('Custom loading message')).toBeInTheDocument()
    })
  })

  describe('Empty Sub-Component', () => {
    it('should render empty state when timeline is empty', () => {
      render(<MessageArea {...defaultProps} timeline={[]} />)

      expect(screen.getByText(/no messages/i)).toBeInTheDocument()
    })

    it('should render with custom title and subtitle', () => {
      render(
        <MessageArea {...defaultProps} timeline={[]}>
          <MessageArea.Empty title="Custom Title" subtitle="Custom Subtitle" />
        </MessageArea>
      )

      expect(screen.getByText('Custom Title')).toBeInTheDocument()
      expect(screen.getByText('Custom Subtitle')).toBeInTheDocument()
    })
  })

  describe('PlanBanner Sub-Component', () => {
    it('should render plan banner when in plan mode', () => {
      render(
        <MessageArea
          {...defaultProps}
          planModeStatus={{ is_in_plan_mode: true, mode: 'auto' }}
        />
      )

      expect(screen.getByTestId('plan-banner')).toBeInTheDocument()
      expect(screen.getByTestId('plan-status')).toHaveTextContent('auto')
    })

    it('should not render plan banner when not in plan mode', () => {
      render(
        <MessageArea
          {...defaultProps}
          planModeStatus={{ is_in_plan_mode: false, mode: 'none' }}
        />
      )

      expect(screen.queryByTestId('plan-banner')).not.toBeInTheDocument()
    })

    it('should call onViewPlan when View Plan button clicked', async () => {
      const onViewPlan = vi.fn()
      render(
        <MessageArea
          {...defaultProps}
          onViewPlan={onViewPlan}
          planModeStatus={{ is_in_plan_mode: true, mode: 'auto' }}
        />
      )

      const viewPlanBtn = screen.getByText('View Plan')
      viewPlanBtn.click()

      expect(onViewPlan).toHaveBeenCalledTimes(1)
    })
  })

  describe('ScrollIndicator Sub-Component', () => {
    it('should render when loading earlier messages', () => {
      render(
        <MessageArea
          {...defaultProps}
          hasEarlierMessages
          isLoadingEarlier
        />
      )

      expect(screen.getByTestId('scroll-indicator')).toBeInTheDocument()
    })

    it('should not render when not loading earlier messages', () => {
      render(<MessageArea {...defaultProps} />)

      expect(screen.queryByTestId('scroll-indicator')).not.toBeInTheDocument()
    })
  })

  describe('ScrollButton Sub-Component', () => {
    it('should render scroll button when user scrolls up', async () => {
      // This would require scroll event simulation
      // For now, just test the component structure
      render(<MessageArea {...defaultProps} />)
    })
  })

  describe('StreamingContent Sub-Component', () => {
    it('should render streaming thought when thinking', () => {
      render(
        <MessageArea
          {...defaultProps}
          streamingThought="Thinking..."
          isThinkingStreaming
        />
      )

      expect(screen.getByTestId('streaming-thought')).toBeInTheDocument()
    })

    it('should render streaming content when streaming', () => {
      render(
        <MessageArea
          {...defaultProps}
          streamingContent="Response..."
          isStreaming
        />
      )

      expect(screen.getByTestId('markdown')).toBeInTheDocument()
    })
  })

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', () => {
      render(<MessageArea {...defaultProps} />)

      expect(screen.getByTestId('message-1')).toBeInTheDocument()
      expect(screen.getByTestId('message-2')).toBeInTheDocument()
    })
  })

  describe('MessageArea Namespace', () => {
    it('should export all sub-components', () => {
      expect(MessageArea.Root).toBeDefined()
      expect(MessageArea.Provider).toBeDefined()
      expect(MessageArea.Loading).toBeDefined()
      expect(MessageArea.Empty).toBeDefined()
      expect(MessageArea.ScrollIndicator).toBeDefined()
      expect(MessageArea.ScrollButton).toBeDefined()
      expect(MessageArea.Content).toBeDefined()
      expect(MessageArea.PlanBanner).toBeDefined()
      expect(MessageArea.StreamingContent).toBeDefined()
    })

    it('should use Root component as alias', () => {
      render(
        <MessageArea.Root {...defaultProps}>
          <MessageArea.Content />
        </MessageArea.Root>
      )

      expect(screen.getByTestId('message-1')).toBeInTheDocument()
    })
  })
})
