/**
 * Tests for EntitiesList Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EntitiesList } from '../../../pages/project/EntitiesList'

// Mock the dependencies
vi.mock('../../../services/graphService', () => ({
  graphService: {
    getEntityTypes: vi.fn().mockResolvedValue({
      entity_types: [
        { entity_type: 'Person', count: 10 },
        { entity_type: 'Organization', count: 5 },
      ]
    }),
    listEntities: vi.fn().mockResolvedValue({
      items: [
        { uuid: '1', name: 'Entity 1', entity_type: 'Person', summary: 'Summary 1' },
        { uuid: '2', name: 'Entity 2', entity_type: 'Organization', summary: 'Summary 2' },
      ],
      total: 2,
    }),
    getEntityRelationships: vi.fn().mockResolvedValue({
      relationships: []
    }),
  },
}))

vi.mock('react-router-dom', () => ({
  useParams: vi.fn(() => ({ projectId: 'test-project-1' })),
}))

vi.mock('react-i18next', () => ({
  useTranslation: vi.fn(() => ({
    t: vi.fn((key: string) => key),
  })),
}))

vi.mock('use-debounce', () => ({
  useDebounce: (value: any) => [value],
}))

vi.mock('../../../components/graph', () => ({
  EntityCard: ({ entity, onClick, isSelected }: any) => (
    <div 
      data-testid={`entity-${entity.uuid}`}
      data-entity-type={entity.entity_type}
      onClick={() => onClick(entity)}
      className={isSelected ? 'selected' : ''}
    >
      {entity.name}
    </div>
  ),
  getEntityTypeColor: vi.fn(() => 'bg-blue-100 text-blue-800'),
}))

vi.mock('../../../components/common', () => ({
  VirtualGrid: ({ items, renderItem, emptyComponent }: any) => (
    <div data-testid="virtual-grid">
      {items.length > 0 ? items.map((item: any) => renderItem(item)) : emptyComponent}
    </div>
  ),
}))

describe('EntitiesList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Root Component', () => {
    it('should render with project ID', () => {
      render(
        <EntitiesList projectId="test-project-1">
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
    })

    it('should render with default sort option', async () => {
      render(
        <EntitiesList defaultSortBy="name">
          <EntitiesList.List />
        </EntitiesList>
      )

      await waitFor(() => {
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
    })

    it('should support custom limit', async () => {
      render(
        <EntitiesList limit={50}>
          <EntitiesList.List />
        </EntitiesList>
      )

      await waitFor(() => {
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
    })
  })

  describe('Header Sub-Component', () => {
    it('should render header', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
      expect(screen.getByText(/entities.title/i)).toBeInTheDocument()
    })

    it('should not render header when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.List />
        </EntitiesList>
      )

      expect(screen.queryByTestId('entities-header')).not.toBeInTheDocument()
    })
  })

  describe('Filters Sub-Component', () => {
    it('should render filters panel', () => {
      render(
        <EntitiesList>
          <EntitiesList.Filters />
        </EntitiesList>
      )

      expect(screen.getByTestId('entities-filters')).toBeInTheDocument()
    })

    it('should not render filters when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.queryByTestId('entities-filters')).not.toBeInTheDocument()
    })
  })

  describe('Stats Sub-Component', () => {
    it('should render stats display', () => {
      render(
        <EntitiesList>
          <EntitiesList.Filters />
          <EntitiesList.Stats />
        </EntitiesList>
      )

      expect(screen.getByTestId('entities-stats')).toBeInTheDocument()
    })

    it('should not render stats when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.queryByTestId('entities-stats')).not.toBeInTheDocument()
    })
  })

  describe('List Sub-Component', () => {
    it('should render entity list', async () => {
      render(
        <EntitiesList>
          <EntitiesList.List />
        </EntitiesList>
      )

      await waitFor(() => {
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
    })

    it('should not render list when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.queryByTestId('virtual-grid')).not.toBeInTheDocument()
    })
  })

  describe('Pagination Sub-Component', () => {
    it('should render pagination controls', async () => {
      // Override mock to return more items for pagination test
      const { graphService } = await import('../../../services/graphService')
      vi.mocked(graphService.listEntities).mockResolvedValueOnce({
        items: Array.from({ length: 25 }, (_, i) => ({
          uuid: `${i}`,
          name: `Entity ${i}`,
          entity_type: 'Person',
          summary: `Summary ${i}`,
        })),
        total: 25,
      })

      render(
        <EntitiesList limit={20}>
          <EntitiesList.List />
          <EntitiesList.Pagination />
        </EntitiesList>
      )

      await waitFor(() => {
        expect(screen.getByTestId('entities-pagination')).toBeInTheDocument()
      })
    })

    it('should not render pagination when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.queryByTestId('entities-pagination')).not.toBeInTheDocument()
    })
  })

  describe('Detail Sub-Component', () => {
    it('should render detail panel', () => {
      render(
        <EntitiesList>
          <EntitiesList.Detail />
        </EntitiesList>
      )

      expect(screen.getByTestId('entities-detail')).toBeInTheDocument()
    })

    it('should not render detail when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      )

      expect(screen.queryByTestId('entities-detail')).not.toBeInTheDocument()
    })
  })

  describe('Multiple Sub-Components Together', () => {
    it('should render all sub-components when included', async () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
          <EntitiesList.Filters />
          <EntitiesList.Stats />
          <EntitiesList.List />
          <EntitiesList.Detail />
        </EntitiesList>
      )

      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
      expect(screen.getByTestId('entities-filters')).toBeInTheDocument()
      expect(screen.getByTestId('entities-stats')).toBeInTheDocument()
      await waitFor(() => {
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
      expect(screen.getByTestId('entities-detail')).toBeInTheDocument()
    })
  })

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', () => {
      render(<EntitiesList projectId="test-project-1" />)

      // Should render default layout with all components
      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
      expect(screen.getByTestId('entities-filters')).toBeInTheDocument()
    })

    it('should support defaultSortBy prop', async () => {
      render(<EntitiesList defaultSortBy="name" />)

      await waitFor(() => {
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument()
      })
    })

    it('should support limit prop', () => {
      render(<EntitiesList limit={50} />)

      expect(screen.getByTestId('entities-filters')).toBeInTheDocument()
    })
  })

  describe('EntitiesList Namespace', () => {
    it('should export all sub-components', () => {
      expect(EntitiesList.Root).toBeDefined()
      expect(EntitiesList.Header).toBeDefined()
      expect(EntitiesList.Filters).toBeDefined()
      expect(EntitiesList.Stats).toBeDefined()
      expect(EntitiesList.List).toBeDefined()
      expect(EntitiesList.Pagination).toBeDefined()
      expect(EntitiesList.Detail).toBeDefined()
    })

    it('should use Root component as alias', () => {
      render(
        <EntitiesList.Root>
          <EntitiesList.Header />
        </EntitiesList.Root>
      )

      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('should handle missing projectId', () => {
      render(<EntitiesList />)

      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
    })

    it('should handle empty children', () => {
      render(<EntitiesList />)

      // Should render default layout
      expect(screen.getByTestId('entities-header')).toBeInTheDocument()
    })
  })
})
