/**
 * Tests for CommunitiesList Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CommunitiesList } from '../../../pages/project/communities'
import type { Community } from '../../../pages/project/communities/types'

// Mock EventSource
global.EventSource = vi.fn(() => ({
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  close: vi.fn(),
  readyState: 2,
})) as any

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
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
    })

    it('should handle empty communities list', async () => {
      ;(graphService.listCommunities as any).mockResolvedValue({
        communities: [],
        total: 0,
      })

      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/no communities found/i)).toBeInTheDocument()
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

      expect(screen.getByText('Rebuild Communities')).toBeInTheDocument()
      expect(screen.getAllByText('Refresh').length).toBeGreaterThan(0)
    })
  })

  describe('Stats Sub-Component', () => {
    it('should display community count stats', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText(/showing.*2.*of.*2/i)).toBeInTheDocument()
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

    it('should be clickable to show details', async () => {
      render(<CommunitiesList />)

      await waitFor(() => {
        expect(screen.getByText('Community 1')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByText('Community 1'))

      await waitFor(() => {
        expect(screen.getByText('Community Details')).toBeInTheDocument()
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

      fireEvent.click(screen.getByText('Community 1'))

      await waitFor(() => {
        expect(screen.getByText('Community Details')).toBeInTheDocument()
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
      expect(CommunitiesList.Info).toBeDefined()
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
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
    })
  })
})
