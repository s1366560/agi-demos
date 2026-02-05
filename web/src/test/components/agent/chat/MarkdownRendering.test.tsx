/**
 * Unit tests for Markdown rendering in Agent Chat components (TDD)
 *
 * Tests for:
 * - AssistantMessage with GFM support (tables, strikethrough, etc.)
 * - ToolExecutionCardDisplay with Markdown results
 * - FinalResponseDisplay with proper Markdown rendering
 * - Image rendering
 * - Link rendering
 *
 * TDD Phase: RED - Tests are written first, will fail initially
 */

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

import '@testing-library/jest-dom/vitest'
import { AssistantMessage } from '../../../../components/agent/chat/AssistantMessage'
import { FinalResponseDisplay } from '../../../../components/agent/chat/FinalResponseDisplay'
import { ToolExecutionCardDisplay } from '../../../../components/agent/chat/MessageStream'

describe('AssistantMessage - Markdown Rendering', () => {
  describe('GitHub Flavored Markdown (GFM) Support', () => {
    it('should render tables correctly', () => {
      const tableContent = `
| Name | Age | City |
|------|-----|------|
| Alice | 25 | NYC |
| Bob | 30 | LA |
      `.trim()

      render(<AssistantMessage content={tableContent} />)

      // Should render table structure
      expect(screen.getByText('Alice')).toBeInTheDocument()
      expect(screen.getByText('Bob')).toBeInTheDocument()
      expect(screen.getByText('NYC')).toBeInTheDocument()
      expect(screen.getByText('LA')).toBeInTheDocument()

      // Should render table element
      const table = screen.getByRole('table')
      expect(table).toBeInTheDocument()
    })

    it('should render strikethrough text', () => {
      render(<AssistantMessage content="~~deleted text~~" />)

      // The strikethrough content should be visible
      expect(screen.getByText('deleted text')).toBeInTheDocument()
    })

    it('should render task lists', () => {
      render(<AssistantMessage content={"- [x] Completed task\n- [ ] Pending task"} />)

      expect(screen.getByText('Completed task')).toBeInTheDocument()
      expect(screen.getByText('Pending task')).toBeInTheDocument()
    })
  })

  describe('Bold and Emphasis', () => {
    it('should render bold text with asterisks', () => {
      render(<AssistantMessage content="This is **bold** text" />)

      expect(screen.getByText('bold')).toBeInTheDocument()
    })

    it('should render bold text with underscores', () => {
      render(<AssistantMessage content="This is __bold__ text" />)

      expect(screen.getByText('bold')).toBeInTheDocument()
    })

    it('should render italic text', () => {
      render(<AssistantMessage content="This is *italic* text" />)

      expect(screen.getByText('italic')).toBeInTheDocument()
    })

    it('should render bold and italic combined', () => {
      render(<AssistantMessage content="This is ***bold italic*** text" />)

      expect(screen.getByText('bold italic')).toBeInTheDocument()
    })
  })

  describe('Code Blocks', () => {
    it('should render inline code', () => {
      render(<AssistantMessage content="Use `const x = 1` in JavaScript" />)

      expect(screen.getByText('const x = 1')).toBeInTheDocument()
    })

    it('should render code blocks with syntax', () => {
      const codeBlock = `
\`\`\`javascript
function hello() {
  return "Hello World";
}
\`\`\`
      `.trim()

      render(<AssistantMessage content={codeBlock} />)

      expect(screen.getByText(/function hello/)).toBeInTheDocument()
      expect(screen.getByText(/Hello World/)).toBeInTheDocument()
    })
  })

  describe('Links and Images', () => {
    it('should render markdown links', () => {
      render(<AssistantMessage content="[OpenAI](https://openai.com)" />)

      const link = screen.getByRole('link', { name: 'OpenAI' })
      expect(link).toBeInTheDocument()
      expect(link).toHaveAttribute('href', 'https://openai.com')
    })

    it('should render markdown images', () => {
      render(<AssistantMessage content="![Alt text](https://example.com/image.png)" />)

      const image = screen.getByRole('img')
      expect(image).toBeInTheDocument()
      expect(image).toHaveAttribute('alt', 'Alt text')
      expect(image).toHaveAttribute('src', 'https://example.com/image.png')
    })

    it('should render inline links with text', () => {
      render(<AssistantMessage content="Visit [Google](https://google.com) for search" />)

      const link = screen.getByRole('link', { name: 'Google' })
      expect(link).toBeInTheDocument()
      expect(screen.getByText(/for search/)).toBeInTheDocument()
    })
  })

  describe('Lists', () => {
    it('should render unordered lists', () => {
      render(<AssistantMessage content={"- Item 1\n- Item 2\n- Item 3"} />)

      expect(screen.getByText('Item 1')).toBeInTheDocument()
      expect(screen.getByText('Item 2')).toBeInTheDocument()
      expect(screen.getByText('Item 3')).toBeInTheDocument()
    })

    it('should render ordered lists', () => {
      render(<AssistantMessage content={"1. First\n2. Second\n3. Third"} />)

      expect(screen.getByText('First')).toBeInTheDocument()
      expect(screen.getByText('Second')).toBeInTheDocument()
      expect(screen.getByText('Third')).toBeInTheDocument()
    })
  })
})

describe('ToolExecutionCardDisplay - Markdown Result Rendering', () => {
  it('should render markdown tables in tool results', () => {
    const tableResult = `
| Entity | Type |
|--------|------|
| Person | Human |
| Organization | Company |
    `.trim()

    render(
      <ToolExecutionCardDisplay
        toolName="GraphQuery"
        status="success"
        result={tableResult}
      />
    )

    expect(screen.getByText('Person')).toBeInTheDocument()
    expect(screen.getByText('Organization')).toBeInTheDocument()
  })

  it('should render bold text in tool results', () => {
    render(
      <ToolExecutionCardDisplay
        toolName="Summary"
        status="success"
        result="**Important:** This is a key finding"
      />
    )

    expect(screen.getByText('Important:')).toBeInTheDocument()
    expect(screen.getByText(/This is a key finding/)).toBeInTheDocument()
  })

  it('should render code blocks in tool results', () => {
    const codeResult = `
\`\`\`
SELECT * FROM entities
\`\`\`
    `.trim()

    render(
      <ToolExecutionCardDisplay
        toolName="GraphQuery"
        status="success"
        result={codeResult}
      />
    )

    expect(screen.getByText(/SELECT/)).toBeInTheDocument()
  })

  it('should render links in tool results', () => {
    render(
      <ToolExecutionCardDisplay
        toolName="WebSearch"
        status="success"
        result="[Result](https://example.com)"
      />
    )

    const link = screen.getByRole('link', { name: 'Result' })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', 'https://example.com')
  })

  it('should render images in tool results', () => {
    render(
      <ToolExecutionCardDisplay
        toolName="ImageGenerator"
        status="success"
        result="![Generated Image](https://example.com/image.png)"
      />
    )

    const image = screen.getByRole('img')
    expect(image).toBeInTheDocument()
    expect(image).toHaveAttribute('src', 'https://example.com/image.png')
  })
})

describe('FinalResponseDisplay - Markdown Rendering', () => {
  it('should render markdown tables in final response', () => {
    const tableContent = `
# Analysis Report

## Summary

| Metric | Value |
|--------|-------|
| Accuracy | 95% |
| Precision | 92% |
    `.trim()

    render(<FinalResponseDisplay content={tableContent} />)

    expect(screen.getByText('Analysis Report')).toBeInTheDocument()
    expect(screen.getByText('Accuracy')).toBeInTheDocument()
    expect(screen.getByText('95%')).toBeInTheDocument()
  })

  it('should render bold and emphasis in final response', () => {
    render(
      <FinalResponseDisplay content="# Report\n\n**Key Finding:** This is **important** data" />
    )

    expect(screen.getByText('Key Finding:')).toBeInTheDocument()
    expect(screen.getByText(/important/)).toBeInTheDocument()
  })

  it('should render code blocks with proper styling', () => {
    const content = `
# Code Example

\`\`\`python
def hello():
    print("Hello World")
\`\`\`
    `.trim()

    render(<FinalResponseDisplay content={content} />)

    expect(screen.getByText(/def hello/)).toBeInTheDocument()
    expect(screen.getByText(/Hello World/)).toBeInTheDocument()
  })
})

describe('Markdown Edge Cases', () => {
  it('should handle empty content gracefully', () => {
    expect(() => render(<AssistantMessage content="" />)).not.toThrow()
  })

  it('should handle special characters', () => {
    render(<AssistantMessage content={"Special: < > & \" '"} />)

    expect(screen.getByText(/Special:/)).toBeInTheDocument()
  })

  it('should handle very long content without crashing', () => {
    const longContent = '# Header\n\n' + 'Repeated text. '.repeat(1000)
    expect(() => render(<AssistantMessage content={longContent} />)).not.toThrow()
  })

  it('should handle malformed markdown gracefully', () => {
    const malformed = '**Bold without closing\n\n`code without closing'
    expect(() => render(<AssistantMessage content={malformed} />)).not.toThrow()
  })
})
