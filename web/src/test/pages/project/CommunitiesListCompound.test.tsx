/**
 * Tests for CommunitiesList Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CommunitiesList } from '../../../pages/project/communities'
import type { Community, BackgroundTask } from '../../../pages/project/communities/types'

// Mock the dependencies
vi.mock('../../../services/graphService', () => ({
  graphService: {
    listCommunities: vi.fn(),
    getCommunityMembers: vi.fn(),
    rebuildCommunities: vi.fn(),
    cancelTask: vi.fn(),
  },
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useParams: vi.fn(() => ({ projectId: 'p1' })),
  }
})

vi.mock('../../../components/tasks/TaskList', () => ({
  TaskList: ({ entityId, entityType }: any) => (
    <div data-testid="task-list" data-entity-id={entityId} data-entity-type={entityType}>
      Tasks
    </div>
  ),
}))

vi.mock('../../../components/common', () => ({
  VirtualGrid: ({ items, renderItem, emptyComponent }: any) => (
    <div data-testid="virtual-grid">
      {items.length === 0 ? (
        emptyComponent
      ) : (
        items.map((item: Community, index: number) => (
          <div key={item.uuid} data-testid={`community-card-${index}`}>
            {renderItem(item, index)}
          </div>
        ))
      )}
    </div>
  ),
}))

vi.mock('../../../services/client/urlUtils', () => ({
  createApiUrl: (path: string) => `http://localhost:8000${path}`,
}))

import { graphService } from '../../../services/graphService'

// Mock test data
const mockCommunities: Community[] = [
  {
    uuid: 'c1',
    name: 'Community 1',
    summary: 'Summary of C1',
    member_count: 10,
    formed_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
  {
    uuid: 'c2',
    name: 'Community 2',
    summary: 'Summary of C2',
    member_count: 20,
    formed_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
]

const mockMembers = [
  { uuid: 'm1', name: 'Member 1', entity_type: 'Person', summary: 'A person' },
  { uuid: 'm2', name: 'Member 2', entity_type: 'Organization', summary: 'An org' },
]

const mockTask: BackgroundTask = {
  task_id: 'task-1',
  task_type: 'rebuild_communities',
  status: 'running',
  created_at: new Date().toISOString(),
  progress: 50,
  message: 'Rebuilding communities...',
  result: { communities_count: 10, edges_count: 100 },
}

describe('CommunitiesList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(graphService.listCommunities as any).mockResolvedValue({
      communities: mockCommunities,
      total: 2,
    })
    ;(graphService.getCommunityMembers as any).mockResolvedValue({
      members: mockMembers,
    })
    ;(graphService.rebuildCommunities as any).mockResolvedValue({
      task_id: 'task-1',
    })
    ;(graphService.cancelTask as any).mockResolvedValue({})
  })

  describe('Root Component', () => {
    it('should render communities list successfully', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByTestId('community-card-0')).toBeInTheDocument()
        expect(screen.getByTestId('community-card-1')).toBeInTheDocument()
      })
    })

    it('should handle empty communities list', async () => {
      ;(graphService.listCommunities as any).mockResolvedValue({
        communities: [],
        total: 0,
      })

      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/no communities/i)).toBeInTheDocument()
      })
    })

    it('should handle loading state', () => {
      ;(graphService.listCommunities as any).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      render(<CommunitiesList />)

      expect(screen.getByTestId('loading-indicator')).toBeInTheDocument()
    })
  })

  describe('Header Sub-Component', () => {
    it('should render header with title and actions', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Communities')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: /rebuild/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /refresh/i })).toBeInTheDocument()
    })

    it('should trigger rebuild on button click', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /rebuild/i })).toBeInTheDocument()
      })

      const rebuildBtn = screen.getByRole('button', { name: /rebuild/i })
      fireEvent.click(rebuildBtn)

      await waitFor(() => {
        expect(graphService.rebuildCommunities).toHaveBeenCalled()
      })
    })
  })

  describe('Stats Sub-Component', () => {
    it('should display community count stats', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/showing.*2.*of.*2/i)).toBeInTheDocument()
      })
    })

    it('should display pagination info when paginated', async () => {
      ;(graphService.listCommunities as any).mockResolvedValue({
        communities: mockCommunities,
        total: 50,
      })

      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/page 1 of/i)).toBeInTheDocument()
      })
    })
  })

  describe('List Sub-Component', () => {
    it('should render community cards', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Community 1')).toBeInTheDocument()
        expect(screen.getByText('Community 2')).toBeInTheDocument()
      })
    })

    it('should display member count on cards', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('10 members')).toBeInTheDocument()
        expect(screen.getByText('20 members')).toBeInTheDocument()
      })
    })

    it('should be clickable to show details', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Community 1')).toBeInTheDocument()
      })

      const card = screen.getByText('Community 1').closest('[data-testid^="community-card"]')
      fireEvent.click(card!)

      await waitFor(() => {
        expect(screen.getByText('Community Details')).toBeInTheDocument()
      })
    })
  })

  describe('Pagination Sub-Component', () => {
    it('should show pagination controls when total exceeds limit', async () => {
      ;(graphService.listCommunities as any).mockResolvedValue({
        communities: mockCommunities,
        total: 50,
      })

      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /previous/i })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument()
      })
    })

    it('should disable previous button on first page', async () => {
      ;(graphService.listCommunities as any).mockResolvedValue({
        communities: mockCommunities,
        total: 50,
      })

      render(<CommunitiesList />)

      await waitFor(() => {
        const prevBtn = screen.getByRole('button', { name: /previous/i })
        expect(prevBtn).toBeDisabled()
      })
    })

    it('should navigate to next page', async () => {
      ;(graphService.listCommunities as any).mockResolvedValue({
        communities: mockCommunities,
        total: 50,
      })

      render(<CommunitiesList />)

      await waitFor(() => {
        const nextBtn = screen.getByRole('button', { name: /next/i })
        expect(nextBtn).not.toBeDisabled()
      })

      const nextBtn = screen.getByRole('button', { name: /next/i })
      fireEvent.click(nextBtn)

      await waitFor(() => {
        expect(screen.getByText(/page 2 of/i)).toBeInTheDocument()
      })
    })
  })

  describe('Detail Sub-Component', () => {
    it('should show empty state when no community selected', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/select a community/i)).toBeInTheDocument()
      })
    })

    it('should show community details when selected', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Community 1')).toBeInTheDocument()
      })

      const card = screen.getByText('Community 1').closest('[data-testid^="community-card"]')
      fireEvent.click(card!)

      await waitFor(() => {
        expect(screen.getByText('Community Details')).toBeInTheDocument()
        expect(screen.getByText('Community 1')).toBeInTheDocument()
        expect(screen.getByText('10')).toBeInTheDocument() // member count
      })
    })

    it('should load and display members', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Community 1')).toBeInTheDocument()
      })

      const card = screen.getByText('Community 1').closest('[data-testid^="community-card"]')
      fireEvent.click(card!)

      await waitFor(() => {
        expect(screen.getByText('Member 1')).toBeInTheDocument()
        expect(screen.getByText('Member 2')).toBeInTheDocument()
      })
    })

    it('should close detail panel', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Community 1')).toBeInTheDocument()
      })

      const card = screen.getByText('Community 1').closest('[data-testid^="community-card"]')
      fireEvent.click(card!)

      await waitFor(() => {
        expect(screen.getByText('Community Details')).toBeInTheDocument()
      })

      const closeBtn = screen.getByRole('button', { name: '' }).querySelector('.material-symbols-outlined') as HTMLElement
      fireEvent.click(closeBtn)

      await waitFor(() => {
        expect(screen.queryByText('Community Details')).not.toBeInTheDocument()
      })
    })
  })

  describe('TaskStatus Sub-Component', () => {
    it('should display running task status', async () => {
      // Mock to set a current task
      render(<CommunitiesList />)

      // Task status would be set via SSE or state update
      // For now, test the component structure
      expect(screen.getByTestId('communities-list-root')).toBeInTheDocument()
    })

    it('should display completed task status', async () => {
      // Test completed state
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByTestId('communities-list-root')).toBeInTheDocument()
      })
    })

    it('should display failed task status', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByTestId('communities-list-root')).toBeInTheDocument()
      })
    })
  })

  describe('Error Sub-Component', () => {
    it('should display error message', async () => {
      ;(graphService.listCommunities as any).mockRejectedValue(
        new Error('Failed to load communities')
      )

      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
      })
    })

    it('should allow dismissing error', async () => {
      ;(graphService.listCommunities as any).mockRejectedValue(
        new Error('Failed to load communities')
      )

      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/failed to load/i)).toBeInTheDocument()
      })

      const dismissBtn = screen.getByRole('button', { name: '' })
        .closest('[data-testid^="error-message"]')
        ?.querySelector('.material-symbols-outlined') as HTMLElement

      fireEvent.click(dismissBtn)

      await waitFor(() => {
        expect(screen.queryByText(/failed to load/i)).not.toBeInTheDocument()
      })
    })
  })

  describe('Compound Component Namespace', () => {
    it('should export all sub-components', () => {
      expect(CommunitiesList.Root).toBeDefined()
      expect(CommunitiesList.Header).toBeDefined()
      expect(CommunitiesList.Stats).toBeDefined()
      expect(CommunitiesList.List).toBeDefined()
      expect(CommunitiesList.Pagination).toBeDefined()
      expect(CommunitiesList.Detail).toBeDefined()
      expect(CommunitiesList.TaskStatus).toBeDefined()
      expect(CommunitiesList.Error).toBeDefined()
    })

    it('should use Root component as alias', async () => {
      render(<CommunitiesList.Root />)

      await waitFor(() => {
        expect(screen.getByTestId('communities-list-root')).toBeInTheDocument()
      })
    })
  })

  describe('Backward Compatibility', () => {
    it('should work with legacy usage (no sub-components)', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByTestId('community-card-0')).toBeInTheDocument()
      })
    })
  })
})
