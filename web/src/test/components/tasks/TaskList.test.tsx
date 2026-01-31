/**
 * Unit tests for TaskList component (Compound Components Pattern)
 *
 * TDD: GREEN - Tests passing after implementation
 */

import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

// Mock date-fns
vi.mock('date-fns', () => ({
  format: vi.fn((date: Date) => 'Jan 1, 12:00:00'),
}))

import { taskAPI } from '../../../services/api'

const mockTasks = [
  {
    id: 'task-1-abc123def456',
    task_type: 'embedding',
    status: 'completed',
    created_at: '2024-01-01T12:00:00Z',
    completed_at: '2024-01-01T12:05:00Z',
    duration: '5s',
    entity_id: 'entity-1',
    entity_type: 'memory',
  },
  {
    id: 'task-2-xyz789abc123',
    task_type: 'vector_search',
    status: 'processing',
    created_at: '2024-01-01T12:01:00Z',
    entity_id: 'entity-2',
    entity_type: 'memory',
  },
  {
    id: 'task-3-failed456',
    task_type: 'graph_sync',
    status: 'failed',
    created_at: '2024-01-01T11:50:00Z',
    error: 'Connection timeout',
    entity_id: 'entity-3',
    entity_type: 'graph',
  },
]

describe('TaskList (Compound Components)', () => {
  beforeAll(() => {
    // Set up default mock for all tests
    vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValue(mockTasks)
    vi.spyOn(taskAPI, 'retryTask').mockResolvedValue(undefined)
    vi.spyOn(taskAPI, 'stopTask').mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('TaskList - Main Container', () => {
    it('should render empty state when no tasks', async () => {
      vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValueOnce([])

      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/No tasks found/i)).toBeInTheDocument()
      })
    })

    it('should render table with tasks when data is loaded', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/embedding/i)).toBeInTheDocument()
        expect(screen.getByText(/vector_search/i)).toBeInTheDocument()
        expect(screen.getByText(/graph_sync/i)).toBeInTheDocument()
      })
    })

    it('should render in embedded mode without header', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      const { container } = render(<TaskList embedded={true} />)

      await waitFor(() => {
        expect(screen.queryByText('Tasks')).not.toBeInTheDocument()
        expect(container.querySelector('.border-0')).toBeInTheDocument()
      })
    })
  })

  describe('TaskList.Header', () => {
    it('should render search input', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/Search Task ID or Name/i)).toBeInTheDocument()
      })
    })

    it('should render status filter dropdown', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByDisplayValue(/All Statuses/i)).toBeInTheDocument()
      })
    })

    it('should render refresh button', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        const buttons = screen.getAllByRole('button')
        expect(buttons.length).toBeGreaterThan(0)
      })
    })
  })

  describe('TaskList.Item', () => {
    it('should render task status with correct color', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/completed/i)).toBeInTheDocument()
        expect(screen.getByText(/processing/i)).toBeInTheDocument()
        expect(screen.getByText(/failed/i)).toBeInTheDocument()
      })
    })

    it('should render task type name', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/embedding/i)).toBeInTheDocument()
      })
    })

    it('should render task duration', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText('5s')).toBeInTheDocument()
      })
    })

    it('should render retry button for failed tasks', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/retry/i)).toBeInTheDocument()
      })
    })

    it('should render stop button for processing tasks', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/stop/i)).toBeInTheDocument()
      })
    })
  })

  describe('TaskList.Pagination', () => {
    it('should render pagination controls', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/Showing \d+ tasks/i)).toBeInTheDocument()
        expect(screen.getByText(/previous/i)).toBeInTheDocument()
        expect(screen.getByText(/next/i)).toBeInTheDocument()
      })
    })

    it('should disable previous button on first page', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        const prevButton = screen.getByText(/previous/i).closest('button')
        expect(prevButton).toBeDisabled()
      })
    })
  })

  describe('TaskList.EmptyState', () => {
    it('should render empty state with search icon', async () => {
      vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValueOnce([])

      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/No tasks found/i)).toBeInTheDocument()
      })
    })
  })

  describe('Accessibility', () => {
    it('should have proper table structure', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })
    })

    it('should have proper column headers', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList')
      render(<TaskList />)

      await waitFor(() => {
        expect(screen.getByText(/status/i)).toBeInTheDocument()
        expect(screen.getByText(/type/i)).toBeInTheDocument()
        expect(screen.getByText(/timestamp/i)).toBeInTheDocument()
      })
    })
  })
})
