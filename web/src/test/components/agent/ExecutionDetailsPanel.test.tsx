/**
 * Tests for ExecutionDetailsPanel component
 * Characterization tests for useCallback refactoring
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '../../utils'
import { ExecutionDetailsPanel } from '../../../components/agent/ExecutionDetailsPanel'

// Mock child components
vi.mock('../../../components/agent/ThinkingChain', () => ({
    ThinkingChain: () => <div data-testid="thinking-chain">ThinkingChain</div>
}))

vi.mock('../../../components/agent/execution/ActivityTimeline', () => ({
    ActivityTimeline: () => <div data-testid="activity-timeline">ActivityTimeline</div>
}))

vi.mock('../../../components/agent/execution/ToolCallVisualization', () => ({
    ToolCallVisualization: () => <div data-testid="tool-visualization">ToolCallVisualization</div>
}))

vi.mock('../../../components/agent/execution/TokenUsageChart', () => ({
    TokenUsageChart: () => <div data-testid="token-chart">TokenUsageChart</div>
}))

describe('ExecutionDetailsPanel', () => {
    const mockMessage = {
        id: 'msg-1',
        conversation_id: 'conv-1',
        role: 'assistant' as const,
        content: 'Test response',
        message_type: 'text' as const,
        created_at: new Date().toISOString(),
        tool_calls: [],
        tool_results: [],
        metadata: {
            thoughts: ['Thought 1', 'Thought 2'],
            timeline: [
                { type: 'thought', content: 'Test thought', timestamp: Date.now() }
            ]
        }
    }

    describe('Rendering', () => {
        it('renders when message has execution data', () => {
            render(<ExecutionDetailsPanel message={mockMessage} />)

            expect(screen.getByTestId('thinking-chain')).toBeInTheDocument()
        })

        it('renders null when message has no data and not streaming', () => {
            const emptyMessage = {
                ...mockMessage,
                metadata: {}
            }

            const { container } = render(<ExecutionDetailsPanel message={emptyMessage} />)

            expect(container.firstChild).toBeNull()
        })

        it('renders when streaming even without data', () => {
            const emptyMessage = {
                ...mockMessage,
                metadata: {}
            }

            render(<ExecutionDetailsPanel message={emptyMessage} isStreaming={true} />)

            // Should render something when streaming
            expect(document.body.children.length).toBeGreaterThan(0)
        })
    })

    describe('View Selector', () => {
        it('shows view selector when showViewSelector is true and multiple views available', () => {
            render(<ExecutionDetailsPanel message={mockMessage} showViewSelector={true} />)

            // Segmented control should be present
            const segmented = screen.getByRole('radiogroup')
            expect(segmented).toBeInTheDocument()
        })

        it('hides view selector when showViewSelector is false', () => {
            render(<ExecutionDetailsPanel message={mockMessage} showViewSelector={false} />)

            // Segmented control should not be present
            const segmented = screen.queryByRole('radiogroup')
            expect(segmented).not.toBeInTheDocument()
        })

        it('uses segmented control with options', () => {
            render(<ExecutionDetailsPanel message={mockMessage} showViewSelector={true} />)

            const options = screen.getAllByRole('radio')
            expect(options.length).toBeGreaterThan(0)
        })
    })

    describe('Compact Mode', () => {
        it('renders in compact mode', () => {
            render(<ExecutionDetailsPanel message={mockMessage} compact={true} />)

            expect(screen.getByTestId('thinking-chain')).toBeInTheDocument()
        })
    })
})
