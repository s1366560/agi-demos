/**
 * Tests for EntitiesList Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { EntitiesList } from '../../../pages/project/EntitiesList';
import { graphService } from '../../../services/graphService';

// Mock the dependencies
vi.mock('../../../services/graphService', () => ({
  graphService: {
    getEntityTypes: vi.fn().mockResolvedValue({
      entity_types: [
        { entity_type: 'Person', count: 10 },
        { entity_type: 'Organization', count: 5 },
      ],
    }),
    listEntities: vi.fn().mockResolvedValue({
      items: [
        { uuid: '1', name: 'Entity 1', entity_type: 'Person', summary: 'Summary 1' },
        { uuid: '2', name: 'Entity 2', entity_type: 'Organization', summary: 'Summary 2' },
      ],
      total: 2,
    }),
    getEntityRelationships: vi.fn().mockResolvedValue({
      relationships: [],
    }),
  },
}));

vi.mock('react-router-dom', () => ({
  useParams: vi.fn(() => ({ tenantId: 'tenant-route-1', projectId: 'test-project-1' })),
}));

vi.mock('react-i18next', () => ({
  useTranslation: vi.fn(() => ({
    t: vi.fn((key: string) => key),
  })),
}));

vi.mock('use-debounce', () => ({
  useDebounce: (value: any) => [value],
}));

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
}));

vi.mock('../../../components/common', () => ({
  VirtualGrid: ({ items, renderItem, emptyComponent }: any) => (
    <div data-testid="virtual-grid">
      {items.length > 0
        ? items.map((item: any, index: number) => (
            <div key={item.uuid ?? item.id ?? index}>{renderItem(item, index)}</div>
          ))
        : emptyComponent}
    </div>
  ),
}));

async function waitForEntityGrid(): Promise<void> {
  await waitFor(() => {
    expect(screen.getByTestId('virtual-grid')).toBeInTheDocument();
  });
}

async function waitForFiltersReady(): Promise<void> {
  await waitFor(() => {
    expect(screen.getByLabelText('project.graph.entities.filter.type')).not.toBeDisabled();
  });
}

const createDeferred = <T,>() => {
  let resolvePromise: (value: T | PromiseLike<T>) => void = () => {};
  let rejectPromise: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  return {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise,
  };
};

describe('EntitiesList Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(graphService.getEntityTypes).mockResolvedValue({
      entity_types: [
        { entity_type: 'Person', count: 10 },
        { entity_type: 'Organization', count: 5 },
      ],
      total: 15,
    });
    vi.mocked(graphService.listEntities).mockResolvedValue({
      items: [
        { uuid: '1', name: 'Entity 1', entity_type: 'Person', summary: 'Summary 1' },
        { uuid: '2', name: 'Entity 2', entity_type: 'Organization', summary: 'Summary 2' },
      ],
      total: 2,
      limit: 50,
      offset: 0,
      has_more: false,
    });
    vi.mocked(graphService.getEntityRelationships).mockResolvedValue({
      relationships: [],
      total: 0,
    });
  });

  describe('Root Component', () => {
    it('should render with project ID', () => {
      render(
        <EntitiesList projectId="test-project-1">
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
    });

    it('should render with default sort option', async () => {
      render(
        <EntitiesList defaultSortBy="name">
          <EntitiesList.List />
        </EntitiesList>
      );

      await waitForEntityGrid();
    });

    it('should support custom limit', async () => {
      render(
        <EntitiesList limit={50}>
          <EntitiesList.List />
        </EntitiesList>
      );

      await waitForEntityGrid();
    });

    it('should pass route tenant context to entity graph requests', async () => {
      render(
        <EntitiesList>
          <EntitiesList.List />
        </EntitiesList>
      );

      await waitFor(() => {
        expect(graphService.listEntities).toHaveBeenCalledWith(
          expect.objectContaining({
            tenant_id: 'tenant-route-1',
            project_id: 'test-project-1',
          })
        );
      });
    });
  });

  describe('Header Sub-Component', () => {
    it('should render header', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
      expect(screen.getByText(/entities.title/i)).toBeInTheDocument();
    });

    it('should not render header when excluded', async () => {
      render(
        <EntitiesList>
          <EntitiesList.List />
        </EntitiesList>
      );

      await waitForEntityGrid();
      expect(screen.queryByTestId('entities-header')).not.toBeInTheDocument();
    });
  });

  describe('Filters Sub-Component', () => {
    it('should render filters panel', async () => {
      render(
        <EntitiesList>
          <EntitiesList.Filters />
        </EntitiesList>
      );

      await waitForFiltersReady();
      expect(screen.getByTestId('entities-filters')).toBeInTheDocument();
    });

    it('should not render filters when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.queryByTestId('entities-filters')).not.toBeInTheDocument();
    });
  });

  describe('Stats Sub-Component', () => {
    it('should render stats display', async () => {
      render(
        <EntitiesList>
          <EntitiesList.Filters />
          <EntitiesList.Stats />
        </EntitiesList>
      );

      await waitForFiltersReady();
      expect(screen.getByTestId('entities-stats')).toBeInTheDocument();
    });

    it('should not render stats when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.queryByTestId('entities-stats')).not.toBeInTheDocument();
    });
  });

  describe('List Sub-Component', () => {
    it('should render entity list', async () => {
      render(
        <EntitiesList>
          <EntitiesList.List />
        </EntitiesList>
      );

      await waitForEntityGrid();
    });

    it('should not render list when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.queryByTestId('virtual-grid')).not.toBeInTheDocument();
    });
  });

  describe('Pagination Sub-Component', () => {
    it('should render pagination controls', async () => {
      const { graphService } = await import('../../../services/graphService');
      vi.mocked(graphService.getEntityTypes).mockResolvedValue({
        entity_types: [
          { entity_type: 'Person', count: 10 },
          { entity_type: 'Organization', count: 5 },
        ],
      });
      vi.mocked(graphService.listEntities).mockResolvedValue({
        items: Array.from({ length: 25 }, (_, i) => ({
          uuid: `${i}`,
          name: `Entity ${i}`,
          entity_type: 'Person',
          summary: `Summary ${i}`,
        })),
        total: 25,
      });

      render(
        <EntitiesList limit={20}>
          <EntitiesList.List />
          <EntitiesList.Pagination />
        </EntitiesList>
      );

      await waitFor(() => {
        expect(screen.getByTestId('entities-pagination')).toBeInTheDocument();
      });
    });

    it('should not render pagination when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.queryByTestId('entities-pagination')).not.toBeInTheDocument();
    });
  });

  describe('Detail Sub-Component', () => {
    it('should render detail panel', () => {
      render(
        <EntitiesList>
          <EntitiesList.Detail />
        </EntitiesList>
      );

      expect(screen.getByTestId('entities-detail')).toBeInTheDocument();
    });

    it('should not render detail when excluded', () => {
      render(
        <EntitiesList>
          <EntitiesList.Header />
        </EntitiesList>
      );

      expect(screen.queryByTestId('entities-detail')).not.toBeInTheDocument();
    });

    it('should render entity relationships from graph API fields', async () => {
      vi.mocked(graphService.getEntityRelationships).mockResolvedValueOnce({
        relationships: [
          {
            edge_id: 'edge-1',
            relation_type: '关联至',
            direction: 'incoming',
            fact: 'EvoMap 关联至 evomap.ai',
            score: 0.8,
            created_at: undefined,
            related_entity: {
              uuid: 'related-1',
              name: 'EvoMap',
              entity_type: 'Organization',
              summary: '',
            },
          },
        ],
        total: 1,
      });

      render(<EntitiesList projectId="test-project-1" />);

      await waitForEntityGrid();
      const entityButton = screen.getByText('Entity 1').closest('button');
      expect(entityButton).toBeTruthy();
      fireEvent.click(entityButton as HTMLButtonElement);

      await waitFor(() => {
        expect(screen.getByText('关联至')).toBeInTheDocument();
      });
      expect(screen.getByText('EvoMap 关联至 evomap.ai')).toBeInTheDocument();
      expect(screen.getByText('EvoMap')).toBeInTheDocument();
      expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
    });
  });

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
      );

      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
      expect(screen.getByTestId('entities-filters')).toBeInTheDocument();
      expect(screen.getByTestId('entities-stats')).toBeInTheDocument();
      await waitFor(() => {
        expect(screen.getByTestId('virtual-grid')).toBeInTheDocument();
      });
      expect(screen.getByTestId('entities-detail')).toBeInTheDocument();
    });
  });

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', async () => {
      render(<EntitiesList projectId="test-project-1" />);

      await waitForEntityGrid();
      // Should render default layout with all components
      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
      expect(screen.getByTestId('entities-filters')).toBeInTheDocument();
    });

    it('should support defaultSortBy prop', async () => {
      render(<EntitiesList defaultSortBy="name" />);

      await waitForEntityGrid();
    });

    it('should support limit prop', async () => {
      render(<EntitiesList limit={50} />);

      await waitForEntityGrid();
      expect(screen.getByTestId('entities-filters')).toBeInTheDocument();
    });
  });

  describe('Async Request Guards', () => {
    it('ignores stale entity and type responses after project changes', async () => {
      const projectAEntityTypes = createDeferred<any>();
      const projectAEntities = createDeferred<any>();
      const projectBEntityTypes = createDeferred<any>();
      const projectBEntities = createDeferred<any>();

      vi.mocked(graphService.getEntityTypes).mockImplementation(({ project_id }: any) => {
        if (project_id === 'project-a') return projectAEntityTypes.promise;
        return projectBEntityTypes.promise;
      });
      vi.mocked(graphService.listEntities).mockImplementation(({ project_id }: any) => {
        if (project_id === 'project-a') return projectAEntities.promise;
        return projectBEntities.promise;
      });

      const { rerender } = render(<EntitiesList projectId="project-a" />);

      await waitFor(() => {
        expect(graphService.listEntities).toHaveBeenCalledWith(
          expect.objectContaining({ project_id: 'project-a' })
        );
      });

      rerender(<EntitiesList projectId="project-b" />);

      await waitFor(() => {
        expect(graphService.listEntities).toHaveBeenCalledWith(
          expect.objectContaining({ project_id: 'project-b' })
        );
      });

      projectBEntityTypes.resolve({
        entity_types: [{ entity_type: 'CurrentType', count: 1 }],
        total: 1,
      });
      projectBEntities.resolve({
        items: [
          {
            uuid: 'current-entity',
            name: 'Current Entity',
            entity_type: 'CurrentType',
            summary: 'Current summary',
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
      });

      expect(await screen.findByText('Current Entity')).toBeInTheDocument();

      projectAEntityTypes.resolve({
        entity_types: [{ entity_type: 'StaleType', count: 1 }],
        total: 1,
      });
      projectAEntities.resolve({
        items: [
          {
            uuid: 'stale-entity',
            name: 'Stale Entity',
            entity_type: 'StaleType',
            summary: 'Stale summary',
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
      });

      await waitFor(() => {
        expect(screen.queryByText('Stale Entity')).not.toBeInTheDocument();
        expect(screen.queryByText('StaleType')).not.toBeInTheDocument();
        expect(screen.getByText('Current Entity')).toBeInTheDocument();
      });
    });

    it('ignores stale relationship responses when selection changes', async () => {
      const entity1Relationships = createDeferred<any>();
      const entity2Relationships = createDeferred<any>();

      vi.mocked(graphService.getEntityRelationships).mockImplementation((entityUuid: string) => {
        if (entityUuid === '1') return entity1Relationships.promise;
        return entity2Relationships.promise;
      });

      render(<EntitiesList projectId="test-project-1" />);

      await waitForEntityGrid();
      const firstEntityButton = screen.getByRole('button', { name: /Entity 1/ });

      fireEvent.click(firstEntityButton);

      await waitFor(() => {
        expect(graphService.getEntityRelationships).toHaveBeenCalledWith('1', { limit: 50 });
      });

      const secondEntityButton = screen.getByRole('button', { name: /Entity 2/ });
      fireEvent.click(secondEntityButton);

      await waitFor(() => {
        expect(graphService.getEntityRelationships).toHaveBeenCalledWith('2', { limit: 50 });
      });

      entity2Relationships.resolve({
        relationships: [
          {
            edge_id: 'edge-current',
            relation_type: 'Current relation',
            direction: 'incoming',
            fact: 'Current relationship fact',
            score: 0.9,
            created_at: undefined,
            related_entity: {
              uuid: 'related-current',
              name: 'Current Related Entity',
              entity_type: 'Person',
              summary: '',
            },
          },
        ],
        total: 1,
      });

      expect(await screen.findByText('Current relation')).toBeInTheDocument();

      entity1Relationships.resolve({
        relationships: [
          {
            edge_id: 'edge-stale',
            relation_type: 'Stale relation',
            direction: 'outgoing',
            fact: 'Stale relationship fact',
            score: 0.7,
            created_at: undefined,
            related_entity: {
              uuid: 'related-stale',
              name: 'Stale Related Entity',
              entity_type: 'Organization',
              summary: '',
            },
          },
        ],
        total: 1,
      });

      await waitFor(() => {
        expect(screen.queryByText('Stale relation')).not.toBeInTheDocument();
        expect(screen.queryByText('Stale relationship fact')).not.toBeInTheDocument();
        expect(screen.getByText('Current relation')).toBeInTheDocument();
      });
    });
  });

  describe('EntitiesList Namespace', () => {
    it('should export all sub-components', () => {
      expect(EntitiesList.Root).toBeDefined();
      expect(EntitiesList.Header).toBeDefined();
      expect(EntitiesList.Filters).toBeDefined();
      expect(EntitiesList.Stats).toBeDefined();
      expect(EntitiesList.List).toBeDefined();
      expect(EntitiesList.Pagination).toBeDefined();
      expect(EntitiesList.Detail).toBeDefined();
    });

    it('should use Root component as alias', () => {
      render(
        <EntitiesList.Root>
          <EntitiesList.Header />
        </EntitiesList.Root>
      );

      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle missing projectId', async () => {
      render(<EntitiesList />);

      await waitForEntityGrid();
      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
    });

    it('should handle empty children', async () => {
      render(<EntitiesList />);

      await waitForEntityGrid();
      // Should render default layout
      expect(screen.getByTestId('entities-header')).toBeInTheDocument();
    });
  });
});
