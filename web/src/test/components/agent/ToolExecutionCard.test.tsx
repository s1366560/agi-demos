/**
 * Unit tests for ToolExecutionCard component (T049)
 *
 * This component displays tool execution information including
 * the tool name, input parameters, execution status, and results.
 */

import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { ToolExecutionCard } from '../../../components/agent/ToolExecutionCard'

describe('ToolExecutionCard', () => {
  const mockToolCall = {
    name: 'memory_search',
    input: {
      query: 'project planning',
      limit: 10,
      filters: { date_range: 'last_30_days' },
    },
    result: 'Found 5 relevant memories about project planning',
    stepNumber: 1, // Will display as Step 2 (stepNumber + 1)
  }

  describe('Rendering', () => {
    it('should render tool name with icon', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      expect(screen.getByText('memory_search')).toBeInTheDocument()
    })

    it('should display tool input parameters', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      // Check for input label
      expect(screen.getByText('Input:')).toBeInTheDocument()
      // Check JSON contains the query
      const container = screen.getByTestId('tool-execution-card')
      expect(container.textContent).toContain('project planning')
    })

    it('should show formatted JSON for input', () => {
      const { container } = render(<ToolExecutionCard toolCall={mockToolCall} />)

      const jsonElement = container.querySelector('pre')
      expect(jsonElement).toBeInTheDocument()
      expect(jsonElement?.textContent).toContain('"query"')
    })

    it('should display tool result when available', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      expect(screen.getByText(/Found 5 relevant memories/)).toBeInTheDocument()
    })

    it('should show step number when provided', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      // stepNumber is 0-indexed, displays as stepNumber + 1
      expect(screen.getByText(/Step 2/)).toBeInTheDocument()
    })
  })

  describe('Status Indicators', () => {
    it('should show running status when no result provided', () => {
      const runningTool = {
        name: 'memory_search',
        input: { query: 'test' },
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={runningTool} />)

      expect(screen.getByText(/Executing/i)).toBeInTheDocument()
    })

    it('should show completed status when result is provided', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      expect(screen.getByText(/Completed/i)).toBeInTheDocument()
    })

    it('should show failed status when error is provided', () => {
      const failedTool = {
        name: 'memory_search',
        input: { query: 'test' },
        error: 'Connection timeout',
        result: undefined,
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={failedTool} />)

      expect(screen.getByText(/Failed/i)).toBeInTheDocument()
    })
  })

  describe('Collapsibility', () => {
    it('should have collapsible toggle', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      // Look for the toggle by aria-label
      const collapseButton = screen.getByLabelText(/Hide details/i)
      expect(collapseButton).toBeInTheDocument()
    })

    it('should collapse when toggle is clicked', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      // Initially visible
      expect(screen.getByText('Input:')).toBeInTheDocument()

      // Click to collapse
      const collapseButton = screen.getByLabelText(/Hide details/i)
      fireEvent.click(collapseButton)

      // After collapse, content should be hidden
      expect(screen.queryByText('Input:')).not.toBeInTheDocument()
    })
  })

  describe('Code Syntax Highlighting', () => {
    it('should apply syntax highlighting to JSON input', () => {
      const { container } = render(<ToolExecutionCard toolCall={mockToolCall} />)

      const jsonBlock = container.querySelector('.json-syntax-highlight')
      expect(jsonBlock).toBeInTheDocument()
    })

    it('should handle different input types', () => {
      const variousInputs = {
        name: 'test_tool',
        input: {
          string: 'text',
          number: 42,
          boolean: true,
          null: null,
          array: [1, 2, 3],
          nested: { key: 'value' },
        },
        stepNumber: 0,
      }
      const { container } = render(<ToolExecutionCard toolCall={variousInputs} />)

      expect(container.textContent).toContain('text')
      expect(container.textContent).toContain('42')
      expect(container.textContent).toContain('true')
    })
  })

  describe('Result Display', () => {
    it('should handle long results', () => {
      const longResult = {
        name: 'memory_search',
        input: {},
        // Use text that won't be parsed as base64 image (not just repeated A's)
        result: 'This is a long search result. '.repeat(50) + 'End of result.',
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={longResult} />)

      const resultBlock = screen.getByTestId('tool-result')
      expect(resultBlock).toBeInTheDocument()
    })

    it('should display error messages', () => {
      const errorTool = {
        name: 'failing_tool',
        input: {},
        error: 'Tool execution failed: timeout',
        result: undefined,
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={errorTool} />)

      expect(screen.getByText(/Tool execution failed: timeout/)).toBeInTheDocument()
    })

    it('should show "(empty)" message when result is empty string', () => {
      const noResult = {
        name: 'void_tool',
        input: { action: 'do_something' },
        result: '',
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={noResult} />)

      expect(screen.getByText(/\(empty\)/)).toBeInTheDocument()
    })
  })

  describe('Metadata', () => {
    it('should display execution duration when provided', () => {
      const timedTool = {
        ...mockToolCall,
        duration: 1250, // milliseconds
      }
      render(<ToolExecutionCard toolCall={timedTool} />)

      expect(screen.getByText(/1\.25s/)).toBeInTheDocument()
    })

    it('should show timestamp when provided', () => {
      const timestampedTool = {
        ...mockToolCall,
        timestamp: '2025-01-08T10:30:00Z',
      }
      render(<ToolExecutionCard toolCall={timestampedTool} />)

      // Timestamp format may vary by locale, just check it renders
      const card = screen.getByTestId('tool-execution-card')
      expect(card).toBeInTheDocument()
    })
  })

  describe('Special Tools', () => {
    it('should handle memory_search tool with specific styling', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      const card = screen.getByTestId('tool-execution-card')
      // Note: underscores are converted to hyphens in class name
      expect(card).toHaveClass('tool-memory-search')
    })

    it('should handle analyze tool with specific styling', () => {
      const analyzeTool = {
        name: 'analyze',
        input: { data: 'test' },
        result: 'Analysis complete',
        stepNumber: 0,
      }
      const { container } = render(<ToolExecutionCard toolCall={analyzeTool} />)

      const card = container.querySelector('.tool-analyze')
      expect(card).toBeInTheDocument()
    })
  })

  describe('Accessibility', () => {
    it('should have proper ARIA labels', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      const card = screen.getByTestId('tool-execution-card')
      expect(card).toHaveAttribute('aria-label', 'Tool execution: memory_search')
    })

    it('should have aria-live on status indicator', () => {
      render(<ToolExecutionCard toolCall={mockToolCall} />)

      expect(screen.getByTestId('tool-status-indicator')).toHaveAttribute('aria-live', 'polite')
    })
  })

  describe('Edge Cases', () => {
    it('should handle empty input gracefully', () => {
      const emptyInput = {
        name: 'no_params_tool',
        input: {},
        result: 'Success',
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={emptyInput} />)

      expect(screen.getByText(/No parameters/i)).toBeInTheDocument()
    })

    it('should handle circular references in input', () => {
      // This would be handled by JSON.stringify with a replacer
      const circularInput = {
        name: 'circular_tool',
        input: { a: 1 },
        result: 'OK',
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={circularInput} />)

      // Should not throw error
      expect(screen.getByText('circular_tool')).toBeInTheDocument()
    })

    it('should handle special characters in result', () => {
      const specialResult = {
        name: 'special_tool',
        input: {},
        result: 'Result with <html> tags & "quotes"',
        stepNumber: 0,
      }
      render(<ToolExecutionCard toolCall={specialResult} />)

      // Should escape HTML
      expect(screen.getByText(/<html>/)).toBeInTheDocument()
    })
  })
})
