/**
 * Unit tests for MessageStream components (TDD)
 *
 * Tests for:
 * - ToolExecutionCardDisplay with various result types
 * - Object vs string result handling
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import {
  ToolExecutionCardDisplay,
  MessageStream,
  UserMessage,
  AgentSection,
  ReasoningLogCard,
} from '../../../../components/agent/chat/MessageStream'

describe('ToolExecutionCardDisplay', () => {
  describe('Result Type Handling', () => {
    it('should render string result correctly', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="test_tool"
          status="success"
          result="Simple string result"
        />
      )

      expect(screen.getByText('Simple string result')).toBeInTheDocument()
    })

    it('should handle object result by converting to JSON string', () => {
      const objectResult = {
        title: 'Search Results',
        output: 'Found 5 items',
        metadata: { count: 5 }
      }

      // This should not throw "Objects are not valid as a React child" error
      expect(() => {
        render(
          <ToolExecutionCardDisplay
            toolName="test_tool"
            status="success"
            result={objectResult as any}
          />
        )
      }).not.toThrow()

      // The component should display the JSON stringified version
      expect(screen.getByText(/Search Results/)).toBeInTheDocument()
    })

    it('should handle null result gracefully', () => {
      expect(() => {
        render(
          <ToolExecutionCardDisplay
            toolName="test_tool"
            status="success"
            result={null as any}
          />
        )
      }).not.toThrow()
    })

    it('should handle undefined result', () => {
      expect(() => {
        render(
          <ToolExecutionCardDisplay
            toolName="test_tool"
            status="success"
          />
        )
      }).not.toThrow()
    })

    it('should handle array result', () => {
      const arrayResult = ['item1', 'item2', 'item3']

      expect(() => {
        render(
          <ToolExecutionCardDisplay
            toolName="test_tool"
            status="success"
            result={arrayResult as any}
          />
        )
      }).not.toThrow()

      expect(screen.getByText(/item1/)).toBeInTheDocument()
    })

    it('should handle nested object result', () => {
      const nestedResult = {
        data: {
          items: [
            { id: 1, name: 'First' },
            { id: 2, name: 'Second' }
          ]
        },
        pagination: { page: 1, total: 2 }
      }

      expect(() => {
        render(
          <ToolExecutionCardDisplay
            toolName="test_tool"
            status="success"
            result={nestedResult as any}
          />
        )
      }).not.toThrow()

      expect(screen.getByText(/First/)).toBeInTheDocument()
      expect(screen.getByText(/Second/)).toBeInTheDocument()
    })
  })

  describe('Status Display', () => {
    it('should show running status', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="running_tool"
          status="running"
        />
      )

      expect(screen.getByText('Running')).toBeInTheDocument()
    })

    it('should show success status', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="success_tool"
          status="success"
          result="Done"
        />
      )

      expect(screen.getByText('Success')).toBeInTheDocument()
    })

    it('should show error status', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="error_tool"
          status="error"
          error="Something went wrong"
        />
      )

      expect(screen.getByText('Failed')).toBeInTheDocument()
      expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    })
  })

  describe('Duration Formatting', () => {
    it('should format milliseconds', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="fast_tool"
          status="success"
          result="Done"
          duration={500}
        />
      )

      // Duration is shown in parentheses after Success badge
      expect(screen.getByText(/\(500ms\)/)).toBeInTheDocument()
    })

    it('should format seconds', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="normal_tool"
          status="success"
          result="Done"
          duration={1500}
        />
      )

      expect(screen.getByText(/\(1\.5s\)/)).toBeInTheDocument()
    })

    it('should format minutes', () => {
      render(
        <ToolExecutionCardDisplay
          toolName="slow_tool"
          status="success"
          result="Done"
          duration={75000}
        />
      )

      expect(screen.getByText(/\(1\.3m\)/)).toBeInTheDocument()
    })
  })
})

describe('MessageStream', () => {
  it('should render children correctly', () => {
    render(
      <MessageStream>
        <UserMessage content="Hello" />
        <AgentSection icon="psychology">
          <ReasoningLogCard steps={['Thinking...']} summary="Thinking" />
        </AgentSection>
      </MessageStream>
    )

    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('Thinking...')).toBeInTheDocument()
  })
})

describe('formatToolResult utility', () => {
  // Helper function to format tool results
  function formatToolResult(result: unknown): string {
    if (result === null || result === undefined) {
      return ''
    }
    if (typeof result === 'string') {
      return result
    }
    return JSON.stringify(result, null, 2)
  }

  it('should return empty string for null', () => {
    expect(formatToolResult(null)).toBe('')
  })

  it('should return empty string for undefined', () => {
    expect(formatToolResult(undefined)).toBe('')
  })

  it('should return string as-is', () => {
    expect(formatToolResult('test string')).toBe('test string')
  })

  it('should convert object to JSON string', () => {
    const obj = { key: 'value', nested: { data: 123 } }
    const result = formatToolResult(obj)
    expect(result).toContain('key')
    expect(result).toContain('value')
    expect(result).toContain('123')
  })

  it('should convert array to JSON string', () => {
    const arr = ['a', 'b', 'c']
    const result = formatToolResult(arr)
    expect(result).toContain('a')
    expect(result).toContain('b')
    expect(result).toContain('c')
  })

  it('should convert number to JSON string', () => {
    expect(formatToolResult(42)).toBe('42')
  })

  it('should convert boolean to JSON string', () => {
    expect(formatToolResult(true)).toBe('true')
  })
})
