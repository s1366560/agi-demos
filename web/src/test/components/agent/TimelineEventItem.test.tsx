/**
 * Tests for TimelineEventItem Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { TimelineEventItem } from '../../../components/agent/TimelineEventItem'

// Mock heavy dependencies
vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <div data-testid="markdown">{children}</div>,
}))

vi.mock('remark-gfm', () => ({
  default: () => ({}),
}))

vi.mock('../../../components/agent/chat/MessageStream', () => ({
  UserMessage: ({ content }: any) => <div data-testid="user-message">{content}</div>,
  AgentSection: ({ children, icon }: any) => (
    <div data-testid="agent-section" data-icon={icon}>
      {children}
    </div>
  ),
  ToolExecutionCardDisplay: ({ toolName, status }: any) => (
    <div data-testid="tool-execution" data-tool={toolName} data-status={status}>
      Tool Execution
    </div>
  ),
  ReasoningLogCard: ({ steps, summary, completed }: any) => (
    <div data-testid="reasoning-log" data-completed={completed}>
      <div data-testid="reasoning-summary">{summary}</div>
      {steps?.map((step: any, i: number) => (
        <div key={i} data-testid="reasoning-step">{step}</div>
      ))}
    </div>
  ),
}))

vi.mock('../../../components/agent/chat/AssistantMessage', () => ({
  AssistantMessage: ({ content }: any) => <div data-testid="assistant-message">{content}</div>,
}))

// Mock timeline events
const mockUserEvent: any = {
  id: '1',
  type: 'user_message',
  content: 'Hello',
  timestamp: Date.now(),
}

const mockAssistantEvent: any = {
  id: '2',
  type: 'assistant_message',
  content: 'Hi there!',
  timestamp: Date.now(),
}

const mockThoughtEvent: any = {
  id: '3',
  type: 'thought',
  content: 'Thinking...',
  timestamp: Date.now(),
}

const mockActEvent: any = {
  id: '4',
  type: 'act',
  toolName: 'search',
  arguments: { query: 'test' },
  timestamp: Date.now(),
}

describe('TimelineEventItem Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Root Component', () => {
    it('should render user message event', () => {
      render(<TimelineEventItem event={mockUserEvent} />)

      expect(screen.getByTestId('user-message')).toBeInTheDocument()
    })

    it('should render assistant message event', () => {
      render(<TimelineEventItem event={mockAssistantEvent} />)

      expect(screen.getByTestId('assistant-message')).toBeInTheDocument()
    })

    it('should render thought event', () => {
      render(<TimelineEventItem event={mockThoughtEvent} />)

      expect(screen.getByTestId('reasoning-log')).toBeInTheDocument()
    })

    it('should render act (tool call) event', () => {
      render(<TimelineEventItem event={mockActEvent} />)

      expect(screen.getByTestId('tool-execution')).toBeInTheDocument()
    })

    it('should return null for unhandled event types', () => {
      const { container } = render(
        <TimelineEventItem event={{ type: 'unknown_type' as any } as any} />
      )

      expect(container.firstChild).toBe(null)
    })
  })

  describe('Backward Compatibility', () => {
    it('should work with legacy props', () => {
      render(<TimelineEventItem event={mockUserEvent} isStreaming={false} />)

      expect(screen.getByTestId('user-message')).toBeInTheDocument()
    })
  })

  describe('TimelineEventItem Namespace', () => {
    it('should export the component', () => {
      expect(TimelineEventItem).toBeDefined()
      expect(TimelineEventItem.displayName).toBe('TimelineEventItem')
    })
  })
})
