/**
 * Tests for EnhancedSearch Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { EnhancedSearch } from '../../../pages/project/EnhancedSearch';

// Mock the dependencies
vi.mock('../../../services/graphService', () => ({
  graphService: {
    advancedSearch: vi.fn().mockResolvedValue({ results: [] }),
    searchByGraphTraversal: vi.fn().mockResolvedValue({ results: [] }),
    searchTemporal: vi.fn().mockResolvedValue({ results: [] }),
    searchWithFacets: vi.fn().mockResolvedValue({ results: [] }),
    searchByCommunity: vi.fn().mockResolvedValue({ results: [] }),
  },
}));

vi.mock('react-router-dom', () => ({
  useParams: vi.fn(() => ({ projectId: 'test-project-1' })),
}));

vi.mock('react-i18next', () => ({
  useTranslation: vi.fn(() => ({
    t: vi.fn((key: string) => key),
  })),
}));

vi.mock('../../../stores/project', () => ({
  useProjectStore: vi.fn(() => ({
    currentProject: { tenant_id: 'tenant-1' },
  })),
}));

vi.mock('@/components/graph/CytoscapeGraph', () => ({
  CytoscapeGraph: () => <div data-testid="cytoscape-graph">Graph</div>,
}));

vi.mock('../../../pages/project/search', () => ({
  SearchForm: ({ onSearch, isConfigOpen }: any) => (
    <div data-testid="search-form">
      <button onClick={onSearch} data-testid="search-button">
        Search
      </button>
      <div data-testid="config-open">{String(isConfigOpen)}</div>
    </div>
  ),
  SearchResults: ({ results, isResultsCollapsed }: any) => (
    <div data-testid="search-results">
      <span data-testid="results-count">{results.length}</span>
      <div data-testid="results-collapsed">{String(isResultsCollapsed)}</div>
    </div>
  ),
  SearchConfig: ({ isConfigOpen }: any) => (
    <div data-testid="search-config" style={{ display: isConfigOpen ? 'block' : 'none' }}>
      Config Panel
    </div>
  ),
}));

describe('EnhancedSearch Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Root Component', () => {
    it('should render with project and tenant IDs', () => {
      render(
        <EnhancedSearch projectId="test-project-1" tenantId="tenant-1">
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });

    it('should render with default search mode', () => {
      render(
        <EnhancedSearch defaultSearchMode="semantic">
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });

    it('should render with default view mode', () => {
      render(
        <EnhancedSearch defaultViewMode="grid">
          <EnhancedSearch.Results />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-results')).toBeInTheDocument();
    });

    it('should support config open state', () => {
      render(
        <EnhancedSearch defaultConfigOpen={false}>
          <EnhancedSearch.Form />
          <EnhancedSearch.Config />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-config')).toBeInTheDocument();
    });
  });

  describe('Form Sub-Component', () => {
    it('should render search form', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });

    it('should not render form when excluded', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Results />
        </EnhancedSearch>
      );

      expect(screen.queryByTestId('search-form')).not.toBeInTheDocument();
    });

    it('should trigger search when search button clicked', async () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Form />
          <EnhancedSearch.Results />
        </EnhancedSearch>
      );

      const searchButton = screen.getByTestId('search-button');
      fireEvent.click(searchButton);

      expect(screen.getByTestId('results-count')).toBeInTheDocument();
    });
  });

  describe('Config Sub-Component', () => {
    it('should render config panel', () => {
      render(
        <EnhancedSearch defaultConfigOpen>
          <EnhancedSearch.Config />
        </EnhancedSearch>
      );

      const config = screen.getByTestId('search-config');
      expect(config).toBeInTheDocument();
      expect(config).toHaveStyle({ display: 'block' });
    });

    it('should not render config when excluded', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.queryByTestId('search-config')).not.toBeInTheDocument();
    });
  });

  describe('Results Sub-Component', () => {
    it('should render results panel', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Results />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-results')).toBeInTheDocument();
    });

    it('should not render results when excluded', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.queryByTestId('search-results')).not.toBeInTheDocument();
    });

    it('should display results count', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Results />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('results-count')).toHaveTextContent('0');
    });
  });

  describe('Graph Sub-Component', () => {
    it('should render graph visualization', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Graph />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('cytoscape-graph')).toBeInTheDocument();
    });

    it('should not render graph when excluded', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.queryByTestId('cytoscape-graph')).not.toBeInTheDocument();
    });
  });

  describe('History Sub-Component', () => {
    it('should render history component', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.History />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-history')).toBeInTheDocument();
    });

    it('should not render history when excluded', () => {
      render(
        <EnhancedSearch>
          <EnhancedSearch.Form />
        </EnhancedSearch>
      );

      expect(screen.queryByTestId('search-history')).not.toBeInTheDocument();
    });
  });

  describe('Multiple Sub-Components Together', () => {
    it('should render all sub-components when included', () => {
      render(
        <EnhancedSearch defaultConfigOpen>
          <EnhancedSearch.Form />
          <EnhancedSearch.Config />
          <EnhancedSearch.Results />
          <EnhancedSearch.Graph />
          <EnhancedSearch.History />
        </EnhancedSearch>
      );

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
      expect(screen.getByTestId('search-config')).toBeInTheDocument();
      expect(screen.getByTestId('search-results')).toBeInTheDocument();
      expect(screen.getByTestId('cytoscape-graph')).toBeInTheDocument();
      expect(screen.getByTestId('search-history')).toBeInTheDocument();
    });
  });

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', () => {
      render(<EnhancedSearch projectId="test-project-1" />);

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
      expect(screen.getByTestId('search-results')).toBeInTheDocument();
      expect(screen.getByTestId('cytoscape-graph')).toBeInTheDocument();
    });

    it('should support defaultSearchMode prop', () => {
      render(<EnhancedSearch defaultSearchMode="graphTraversal" />);

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });

    it('should support defaultViewMode prop', () => {
      render(<EnhancedSearch defaultViewMode="list" />);

      expect(screen.getByTestId('search-results')).toBeInTheDocument();
    });

    it('should support defaultConfigOpen prop', () => {
      render(<EnhancedSearch defaultConfigOpen={false} />);

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });
  });

  describe('EnhancedSearch Namespace', () => {
    it('should export all sub-components', () => {
      expect(EnhancedSearch.Root).toBeDefined();
      expect(EnhancedSearch.Form).toBeDefined();
      expect(EnhancedSearch.Config).toBeDefined();
      expect(EnhancedSearch.Results).toBeDefined();
      expect(EnhancedSearch.Graph).toBeDefined();
      expect(EnhancedSearch.Error).toBeDefined();
      expect(EnhancedSearch.History).toBeDefined();
    });

    it('should use Root component as alias', () => {
      render(
        <EnhancedSearch.Root>
          <EnhancedSearch.Form />
        </EnhancedSearch.Root>
      );

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle missing projectId', () => {
      render(<EnhancedSearch />);

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });

    it('should handle empty children', () => {
      render(<EnhancedSearch />);

      expect(screen.getByTestId('search-form')).toBeInTheDocument();
    });
  });
});
