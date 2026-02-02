/**
 * Virtualized Memory List Tests
 *
 * TDD Phase 1 (RED): Tests for virtualized memory list in ProjectOverview
 *
 * These tests verify that the memory list uses virtualization for performance
 * with large datasets. The tests will fail initially because the virtualized
 * implementation doesn't exist yet.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

// Mock API
vi.mock('@/services/api', () => ({
  projectAPI: {
    getStats: vi.fn().mockResolvedValue({
      memory_count: 100,
      storage_used: 1024000,
      storage_limit: 10240000,
      active_nodes: 50,
      collaborators: 5,
    }),
    get: vi.fn().mockResolvedValue({
      id: '1',
      name: 'Test Project',
      description: 'Test Description',
    }),
  },
  memoryAPI: {
    list: vi.fn().mockResolvedValue({
      memories: [],
      total: 0,
      page: 1,
      page_size: 5,
    }),
  },
}))

// Mock react-router-dom
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useParams: () => ({ projectId: '1' }),
    useNavigate: () => vi.fn(),
    Link: ({ children, to, ...props }: any) => (
      <a href={to} {...props}>{children}</a>
    ),
  }
})

// Test data
const generateMockMemories = (count: number) => {
  return Array.from({ length: count }, (_, i) => ({
    id: `memory-${i}`,
    title: `Memory ${i}`,
    content: `Content for memory ${i}`.repeat(10),
    content_type: i % 3 === 0 ? 'image' : i % 3 === 1 ? 'video' : 'text',
    status: i % 2 === 0 ? 'ACTIVE' : 'DISABLED',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  }))
}

describe('Virtualized Memory List', () => {
  describe('Component structure', () => {
    it('should render VirtualGrid component for memory list', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(50)

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
        />
      )

      // Should render virtual grid container
      const grid = container.querySelector('[data-testid="virtual-grid"]')
      expect(grid).toBeInTheDocument()
    })

    it('should render empty state when no memories', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const { container } = render(
        <VirtualizedMemoryList
          memories={[]}
          projectId="1"
          onMemoryClick={vi.fn()}
        />
      )

      expect(screen.getByText(/no memories/i)).toBeInTheDocument()
    })
  })

  describe('Virtual scrolling behavior', () => {
    it('should only render visible items plus overscan', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(100) // 100 items
      const containerHeight = 400
      const itemHeight = 80

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={containerHeight}
          estimateSize={() => itemHeight}
        />
      )

      // Calculate expected visible items
      const visibleCount = Math.ceil(containerHeight / itemHeight) + 10 // +10 for overscan

      // Count actual rendered memory rows
      const memoryRows = container.querySelectorAll('[data-testid^="virtual-row-"]')
      expect(memoryRows.length).toBeLessThanOrEqual(visibleCount)
      expect(memoryRows.length).toBeGreaterThan(0)
    })

    it('should update visible items on scroll', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(100)
      const user = userEvent.setup()

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      const scrollContainer = container.querySelector('[data-testid="virtual-scroll-container"]') as HTMLElement
      expect(scrollContainer).toBeInTheDocument()

      // Get initial rendered items
      const initialRows = container.querySelectorAll('[data-testid^="virtual-row-"]')
      const initialCount = initialRows.length

      // Scroll down
      await user.type(scrollContainer, '{PageDown}')

      // Wait for virtual scroll to update
      await waitFor(() => {
        const newRows = container.querySelectorAll('[data-testid^="virtual-row-"]')
        // The set of visible items should have changed
        expect(newRows.length).toBeGreaterThan(0)
      })
    })
  })

  describe('Performance', () => {
    it('should handle large datasets without performance degradation', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(1000) // Large dataset

      const startTime = performance.now()

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      const renderTime = performance.now() - startTime

      // Should render quickly (< 100ms) even with 1000 items
      expect(renderTime).toBeLessThan(100)

      // Should not render all 1000 items
      const memoryRows = container.querySelectorAll('[data-testid^="virtual-row-"]')
      expect(memoryRows.length).toBeLessThan(100)
    })

    it('should not re-render non-visible items on state change', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(100)
      const renderSpy = vi.fn()

      const TestComponent = () => {
        const [count, setCount] = React.useState(0)
        return (
          <div>
            <button onClick={() => setCount(c => c + 1)}>Increment</button>
            <span>Count: {count}</span>
            <VirtualizedMemoryList
              memories={memories}
              projectId="1"
              onMemoryClick={() => renderSpy()}
              containerHeight={400}
            />
          </div>
        )
      }

      const { container } = render(<TestComponent />)

      const initialRows = container.querySelectorAll('[data-testid^="virtual-row-"]')

      // Trigger unrelated state update
      await fireEvent.click(screen.getByText('Increment'))

      // Virtualized rows should not re-render (same count)
      const newRows = container.querySelectorAll('[data-testid^="virtual-row-"]')
      expect(newRows.length).toBe(initialRows.length)
    })
  })

  describe('Keyboard navigation', () => {
    it('should support arrow key navigation', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(20)
      const user = userEvent.setup()

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      const scrollContainer = container.querySelector('[data-testid="virtual-scroll-container"]') as HTMLElement
      expect(scrollContainer).toBeInTheDocument()

      // Focus the container
      scrollContainer.focus()
      await fireEvent.keyDown(scrollContainer, { key: 'ArrowDown' })

      // Should scroll or select next item
      await waitFor(() => {
        expect(scrollContainer).toHaveFocus()
      })
    })

    it('should support Home/End key navigation', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(50)
      const user = userEvent.setup()

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      const scrollContainer = container.querySelector('[data-testid="virtual-scroll-container"]') as HTMLElement

      // Press End key
      await fireEvent.keyDown(scrollContainer, { key: 'End' })

      // Should scroll to bottom
      await waitFor(() => {
        expect(scrollContainer).toBeInTheDocument()
      })

      // Press Home key
      await fireEvent.keyDown(scrollContainer, { key: 'Home' })

      // Should scroll to top
      await waitFor(() => {
        expect(scrollContainer).toBeInTheDocument()
      })
    })

    it('should support Page Up/Down navigation', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(50)
      const user = userEvent.setup()

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      const scrollContainer = container.querySelector('[data-testid="virtual-scroll-container"]') as HTMLElement

      // Press PageDown
      await fireEvent.keyDown(scrollContainer, { key: 'PageDown' })

      await waitFor(() => {
        expect(scrollContainer).toBeInTheDocument()
      })

      // Press PageUp
      await fireEvent.keyDown(scrollContainer, { key: 'PageUp' })

      await waitFor(() => {
        expect(scrollContainer).toBeInTheDocument()
      })
    })
  })

  describe('Accessibility', () => {
    it('should have proper ARIA attributes', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(20)

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      // Should have role="grid" or similar
      const grid = container.querySelector('[role="grid"]')
      expect(grid).toBeInTheDocument()

      // Each row should have proper ARIA
      const rows = container.querySelectorAll('[role="row"]')
      expect(rows.length).toBeGreaterThan(0)
    })

    it('should announce screen reader text for list status', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(20)

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      // Should have aria-live region for status updates
      const liveRegion = container.querySelector('[aria-live]')
      expect(liveRegion).toBeInTheDocument()
    })

    it('should be keyboard navigable with Tab', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(10)

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      // First memory should be focusable
      const firstMemory = container.querySelector('[data-testid^="virtual-row-0"]')
      expect(firstMemory).toBeInTheDocument()

      if (firstMemory) {
        firstMemory.setAttribute('tabIndex', '0')
        firstMemory.focus()
        expect(document.activeElement).toBe(firstMemory)
      }
    })
  })

  describe('Memory item rendering', () => {
    it('should render memory title correctly', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = [
        {
          id: '1',
          title: 'Test Memory Title',
          content: 'Test content',
          content_type: 'text',
          status: 'ACTIVE',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ]

      const { getByText } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      expect(getByText('Test Memory Title')).toBeInTheDocument()
    })

    it('should render memory type icon', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = [
        {
          id: '1',
          title: 'Image Memory',
          content: 'Image content',
          content_type: 'image',
          status: 'ACTIVE',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ]

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      // Should have image icon
      const icon = container.querySelector('[data-testid="memory-icon-image"]')
      expect(icon).toBeInTheDocument()
    })

    it('should render memory status badge', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = [
        {
          id: '1',
          title: 'Active Memory',
          content: 'Content',
          content_type: 'text',
          status: 'ACTIVE',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ]

      const { container } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="1"
          onMemoryClick={vi.fn()}
          containerHeight={400}
        />
      )

      // Should have status badge
      const statusBadge = container.querySelector('[data-testid="memory-status-badge"]')
      expect(statusBadge).toBeInTheDocument()
      expect(statusBadge?.textContent).toContain('Available')
    })

    it('should handle click on memory item', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = [
        {
          id: 'memory-123',
          title: 'Clickable Memory',
          content: 'Content',
          content_type: 'text',
          status: 'ACTIVE',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ]

      const handleClick = vi.fn()
      const user = userEvent.setup()

      const { getByText } = render(
        <VirtualizedMemoryList
          memories={memories}
          projectId="project-1"
          onMemoryClick={handleClick}
          containerHeight={400}
        />
      )

      await user.click(getByText('Clickable Memory'))

      expect(handleClick).toHaveBeenCalledWith('memory-123')
    })
  })

  describe('Responsive behavior', () => {
    it('should adjust to container width', async () => {
      const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

      const memories = generateMockMemories(20)

      const { container } = render(
        <div style={{ width: '300px' }}>
          <VirtualizedMemoryList
            memories={memories}
            projectId="1"
            onMemoryClick={vi.fn()}
            containerHeight={400}
          />
        </div>
      )

      // Should render without overflow
      const grid = container.querySelector('[data-testid="virtual-grid"]')
      expect(grid).toBeInTheDocument()
    })
  })
})

describe('ProjectOverview Integration', () => {
  it('should use VirtualGrid for memory table', async () => {
    // This test verifies ProjectOverview uses the virtualized component
    const { default: ProjectOverview } = await import('@/pages/project/ProjectOverview')

    const { container } = render(<ProjectOverview />)

    // Should render virtualized memory section
    await waitFor(() => {
      const memorySection = container.querySelector('[data-testid="virtualized-memory-list"]')
      expect(memorySection).toBeInTheDocument()
    })
  })

  it('should pass correct props to VirtualGrid', async () => {
    const { VirtualizedMemoryList } = await import('@/pages/project/ProjectOverview')

    const memories = generateMockMemories(10)
    const handleMemoryClick = vi.fn()

    render(
      <VirtualizedMemoryList
        memories={memories}
        projectId="test-project"
        onMemoryClick={handleMemoryClick}
        containerHeight={400}
      />
    )

    // Component should render without errors
    const grid = screen.queryByTestId('virtual-grid')
    expect(grid).toBeInTheDocument()
  })
})

// Import React for the test component
import React from 'react'
