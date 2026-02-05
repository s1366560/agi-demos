/**
 * Unit tests for ThoughtBubble component (T048)
 *
 * This component displays the agent's thinking process at both
 * work-level and task-level with collapsible sections.
 */

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import '@testing-library/jest-dom/vitest'
import { ThoughtBubble } from '../../../components/agent/ThoughtBubble'

describe('ThoughtBubble', () => {
  describe('Rendering', () => {
    it('should render thought bubble with content', () => {
      render(<ThoughtBubble thought="I need to search for memories about project planning" level="task" />)

      expect(screen.getByText(/I need to search for memories/)).toBeInTheDocument()
    })

    it('should display work-level thinking with appropriate label', () => {
      render(<ThoughtBubble thought="This is a complex query requiring multiple steps" level="work" />)

      expect(screen.getByText(/work-level thinking/i)).toBeInTheDocument()
    })

    it('should display task-level thinking with appropriate label', () => {
      render(<ThoughtBubble thought="Searching memory database now" level="task" />)

      expect(screen.getByText(/task-level thinking/i)).toBeInTheDocument()
    })

    it('should show bulb icon for thinking indicator', () => {
      const { container } = render(<ThoughtBubble thought="Thinking..." level="task" />)

      const icon = container.querySelector('.anticon-bulb')
      expect(icon).toBeInTheDocument()
    })
  })

  describe('Styling', () => {
    it('should apply different colors for work vs task level', () => {
      const { rerender } = render(<ThoughtBubble thought="Thought" level="work" />)

      const workBubble = screen.getByTestId('thought-bubble')
      expect(workBubble).toHaveClass('thought-work')

      rerender(<ThoughtBubble thought="Thought" level="task" />)

      const taskBubble = screen.getByTestId('thought-bubble')
      expect(taskBubble).toHaveClass('thought-task')
    })

    it('should have text styling', () => {
      render(<ThoughtBubble thought="Thinking..." level="task" />)

      const thoughtText = screen.getByText('Thinking...')
      expect(thoughtText).toBeInTheDocument()
    })
  })

  describe('Collapsibility', () => {
    it('should be collapsible for long thoughts', () => {
      const longThought = 'This is a very long thought that should definitely be collapsible because it exceeds the 100 character threshold that the component uses to determine whether to show the collapse button or not in the interface.'
      render(<ThoughtBubble thought={longThought} level="task" />)

      // The component uses aria-label="Collapse thought" on Typography.Link
      const collapseButton = screen.getByLabelText(/Collapse thought/i)
      expect(collapseButton).toBeInTheDocument()
    })

    it('should not show collapse button for short thoughts', () => {
      render(<ThoughtBubble thought="Short thought" level="task" />)

      const collapseButton = screen.queryByLabelText(/collapse thought/i)
      expect(collapseButton).not.toBeInTheDocument()
    })

    it('should toggle visibility when clicked', () => {
      const longThought = 'This is a very long thought that should definitely be collapsible because it exceeds the 100 character threshold that the component uses to determine whether to show the collapse button or not in the interface.'
      render(<ThoughtBubble thought={longThought} level="task" />)

      const thought = screen.getByText(/This is a very long thought/)
      const collapseButton = screen.getByLabelText(/Collapse thought/i)

      expect(thought).toBeVisible()

      fireEvent.click(collapseButton)
      // After collapse, should show truncated text
      expect(screen.getByText(/This is a very long thought that should definitely be collapsible because it exceeds the 100 c/)).toBeInTheDocument()
    })

    it('should show truncated preview when collapsed', () => {
      const longThought = 'This is a very long thought that should be truncated when the bubble is collapsed to save space in the chat interface while still giving the user an idea of what the agent is thinking about right now during this conversation.'
      render(<ThoughtBubble thought={longThought} level="task" />)

      const collapseButton = screen.getByLabelText(/Collapse thought/i)

      fireEvent.click(collapseButton)

      // Should show truncated preview (100 chars + ...)
      expect(screen.getByText(/This is a very long thought that should be truncated when the bubble is collapsed to save space in t.../)).toBeInTheDocument()
    })
  })

  describe('Step Context', () => {
    it('should display step number when provided', () => {
      render(
        <ThoughtBubble
          thought="Searching for relevant memories"
          level="task"
          stepNumber={1}
        />
      )

      // stepNumber is 0-indexed in component (displays stepNumber + 1)
      expect(screen.getByText(/Step 2/)).toBeInTheDocument()
    })

    it('should show step description when provided', () => {
      render(
        <ThoughtBubble
          thought="Analyzing results"
          level="task"
          stepNumber={2}
          stepDescription="Analyze retrieved memories"
        />
      )

      expect(screen.getByText(/Analyze retrieved memories/i)).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('should have proper ARIA labels', () => {
      render(<ThoughtBubble thought="Thinking..." level="work" />)

      const bubble = screen.getByTestId('thought-bubble')
      expect(bubble).toHaveAttribute('aria-label', 'Agent thinking process')
    })

    it('should announce thought updates to screen readers', () => {
      const { rerender } = render(<ThoughtBubble thought="Initial thought" level="task" />)

      rerender(<ThoughtBubble thought="Updated thought" level="task" />)

      expect(screen.getByText('Updated thought')).toBeInTheDocument()
    })
  })

  describe('Animation', () => {
    it('should show loading animation when isThinking is true', () => {
      render(<ThoughtBubble thought="Still thinking..." level="task" isThinking={true} />)

      const loadingIndicator = screen.getByTestId('thinking-indicator')
      expect(loadingIndicator).toHaveClass('thinking-animation')
    })

    it('should stop animation when isThinking is false', () => {
      render(<ThoughtBubble thought="Done thinking" level="task" isThinking={false} />)

      const icon = screen.getByTestId('thinking-indicator')
      expect(icon).toBeInTheDocument()
      expect(icon).not.toHaveClass('thinking-animation')
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty thought gracefully', () => {
      render(<ThoughtBubble thought="" level="task" />)

      // Empty thought shows "Processing..." or "Thinking..."
      expect(screen.getByText(/Processing/i)).toBeInTheDocument()
    })

    it('should handle very long thoughts with scrolling', () => {
      const longThought = 'A'.repeat(1000)
      render(<ThoughtBubble thought={longThought} level="work" />)

      const bubble = screen.getByTestId('thought-bubble')
      expect(bubble).toBeInTheDocument()
    })

    it('should handle special characters in thought', () => {
      const specialThought = 'Thinking about <script>alert("test")</script> and symbols: < > & " \''
      render(<ThoughtBubble thought={specialThought} level="task" />)

      // Should be escaped, not rendered as HTML
      expect(screen.getByText(/<script>/)).toBeInTheDocument()
    })
  })
})
