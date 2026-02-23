/**
 * useSearchState Hook Tests
 *
 * Tests for the custom hook that manages EnhancedSearch state.
 * This hook extracts state management logic from the EnhancedSearch component.
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useSearchState } from '@/hooks/useSearchState';

// Mock the graphService
vi.mock('@/services/graphService', () => ({
  graphService: {
    advancedSearch: vi.fn(),
    searchByGraphTraversal: vi.fn(),
    searchTemporal: vi.fn(),
    searchWithFacets: vi.fn(),
    searchByCommunity: vi.fn(),
  },
}));

describe('useSearchState', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Initial State', () => {
    it('should initialize with default search mode as semantic', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.searchMode).toBe('semantic');
    });

    it('should initialize with empty query and results', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.query).toBe('');
      expect(result.current.results).toEqual([]);
    });

    it('should initialize with loading and error as null/false', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBe(null);
    });

    it('should initialize with default view mode as grid', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.viewMode).toBe('grid');
    });

    it('should initialize with results not collapsed', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.isResultsCollapsed).toBe(false);
    });

    it('should initialize with config panel open', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.isConfigOpen).toBe(true);
    });
  });

  describe('Search Mode Management', () => {
    it('should change search mode', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setSearchMode('graphTraversal');
      });

      expect(result.current.searchMode).toBe('graphTraversal');
    });

    it('should support all search modes', () => {
      const { result } = renderHook(() => useSearchState());
      const modes = ['semantic', 'graphTraversal', 'temporal', 'faceted', 'community'] as const;

      modes.forEach((mode) => {
        act(() => {
          result.current.setSearchMode(mode);
        });
        expect(result.current.searchMode).toBe(mode);
      });
    });
  });

  describe('Query Management', () => {
    it('should update query', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setQuery('test query');
      });

      expect(result.current.query).toBe('test query');
    });

    it('should clear query', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setQuery('test query');
      });
      expect(result.current.query).toBe('test query');

      act(() => {
        result.current.setQuery('');
      });
      expect(result.current.query).toBe('');
    });
  });

  describe('Results Management', () => {
    it('should set results', () => {
      const { result } = renderHook(() => useSearchState());
      const mockResults = [
        { content: 'test', score: 0.9, metadata: { type: 'test' }, source: 'test' },
      ];

      act(() => {
        result.current.setResults(mockResults);
      });

      expect(result.current.results).toEqual(mockResults);
    });

    it('should clear results', () => {
      const { result } = renderHook(() => useSearchState());
      const mockResults = [
        { content: 'test', score: 0.9, metadata: { type: 'test' }, source: 'test' },
      ];

      act(() => {
        result.current.setResults(mockResults);
      });
      expect(result.current.results).toHaveLength(1);

      act(() => {
        result.current.setResults([]);
      });
      expect(result.current.results).toHaveLength(0);
    });

    it('should compute highlight node IDs from results', () => {
      const { result } = renderHook(() => useSearchState());
      const mockResults = [
        { content: 'test', score: 0.9, metadata: { uuid: 'uuid-1' }, source: 'test' },
        { content: 'test2', score: 0.8, metadata: { uuid: 'uuid-2' }, source: 'test' },
      ];

      act(() => {
        result.current.setResults(mockResults);
      });

      expect(result.current.highlightNodeIds).toEqual(['uuid-1', 'uuid-2']);
    });

    it('should handle results without UUIDs', () => {
      const { result } = renderHook(() => useSearchState());
      const mockResults = [
        { content: 'test', score: 0.9, metadata: { type: 'test' }, source: 'test' },
      ];

      act(() => {
        result.current.setResults(mockResults);
      });

      expect(result.current.highlightNodeIds).toEqual([]);
    });
  });

  describe('Loading State', () => {
    it('should set loading state', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setLoading(true);
      });

      expect(result.current.loading).toBe(true);

      act(() => {
        result.current.setLoading(false);
      });

      expect(result.current.loading).toBe(false);
    });
  });

  describe('Error State', () => {
    it('should set error state', () => {
      const { result } = renderHook(() => useSearchState());
      const errorMessage = 'Search failed';

      act(() => {
        result.current.setError(errorMessage);
      });

      expect(result.current.error).toBe(errorMessage);
    });

    it('should clear error state', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setError('Error');
      });
      expect(result.current.error).toBe('Error');

      act(() => {
        result.current.setError(null);
      });
      expect(result.current.error).toBe(null);
    });
  });

  describe('View Mode Management', () => {
    it('should toggle view mode between grid and list', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.viewMode).toBe('grid');

      act(() => {
        result.current.setViewMode('list');
      });

      expect(result.current.viewMode).toBe('list');

      act(() => {
        result.current.setViewMode('grid');
      });

      expect(result.current.viewMode).toBe('grid');
    });
  });

  describe('Results Collapse Management', () => {
    it('should toggle results collapse state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.isResultsCollapsed).toBe(false);

      act(() => {
        result.current.toggleResultsCollapse();
      });

      expect(result.current.isResultsCollapsed).toBe(true);

      act(() => {
        result.current.toggleResultsCollapse();
      });

      expect(result.current.isResultsCollapsed).toBe(false);
    });
  });

  describe('Config Panel Management', () => {
    it('should toggle config panel open state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.isConfigOpen).toBe(true);

      act(() => {
        result.current.toggleConfigOpen();
      });

      expect(result.current.isConfigOpen).toBe(false);

      act(() => {
        result.current.toggleConfigOpen();
      });

      expect(result.current.isConfigOpen).toBe(true);
    });
  });

  describe('Graph Traversal State', () => {
    it('should manage graph traversal specific state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.startEntityUuid).toBe('');
      expect(result.current.maxDepth).toBe(2);
      expect(result.current.relationshipTypes).toEqual([]);

      act(() => {
        result.current.setStartEntityUuid('uuid-123');
        result.current.setMaxDepth(3);
        result.current.setRelationshipTypes(['RELATES_TO', 'MENTIONS']);
      });

      expect(result.current.startEntityUuid).toBe('uuid-123');
      expect(result.current.maxDepth).toBe(3);
      expect(result.current.relationshipTypes).toEqual(['RELATES_TO', 'MENTIONS']);
    });

    it('should limit max depth between 1 and 5', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setMaxDepth(0);
      });
      expect(result.current.maxDepth).toBe(1);

      act(() => {
        result.current.setMaxDepth(10);
      });
      expect(result.current.maxDepth).toBe(5);
    });
  });

  describe('Semantic Search State', () => {
    it('should manage semantic search specific state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.retrievalMode).toBe('hybrid');
      expect(result.current.strategy).toBe('COMBINED_HYBRID_SEARCH_RRF');
      expect(result.current.focalNode).toBe('');
      expect(result.current.crossEncoder).toBe('bge');

      act(() => {
        result.current.setRetrievalMode('nodeDistance');
        result.current.setStrategy('EDGE_HYBRID_SEARCH_CROSS_ENCODER');
        result.current.setFocalNode('node-uuid');
        result.current.setCrossEncoder('openai');
      });

      expect(result.current.retrievalMode).toBe('nodeDistance');
      expect(result.current.strategy).toBe('EDGE_HYBRID_SEARCH_CROSS_ENCODER');
      expect(result.current.focalNode).toBe('node-uuid');
      expect(result.current.crossEncoder).toBe('openai');
    });
  });

  describe('Temporal Search State', () => {
    it('should manage temporal search specific state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.timeRange).toBe('last30');
      expect(result.current.customTimeRange).toEqual({});

      act(() => {
        result.current.setTimeRange('custom');
        result.current.setCustomTimeRange({
          since: '2024-01-01T00:00:00Z',
          until: '2024-12-31T23:59:59Z',
        });
      });

      expect(result.current.timeRange).toBe('custom');
      expect(result.current.customTimeRange).toEqual({
        since: '2024-01-01T00:00:00Z',
        until: '2024-12-31T23:59:59Z',
      });
    });
  });

  describe('Faceted Search State', () => {
    it('should manage faceted search specific state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.selectedEntityTypes).toEqual([]);
      expect(result.current.selectedTags).toEqual([]);

      act(() => {
        result.current.setSelectedEntityTypes(['Person', 'Organization']);
        result.current.setSelectedTags(['architecture', 'meeting']);
      });

      expect(result.current.selectedEntityTypes).toEqual(['Person', 'Organization']);
      expect(result.current.selectedTags).toEqual(['architecture', 'meeting']);
    });

    it('should toggle entity types', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.toggleEntityType('Person');
      });
      expect(result.current.selectedEntityTypes).toEqual(['Person']);

      act(() => {
        result.current.toggleEntityType('Person');
      });
      expect(result.current.selectedEntityTypes).toEqual([]);

      act(() => {
        result.current.toggleEntityType('Organization');
        result.current.toggleEntityType('Person');
      });
      expect(result.current.selectedEntityTypes).toEqual(['Organization', 'Person']);
    });

    it('should toggle tags', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.toggleTag('architecture');
      });
      expect(result.current.selectedTags).toEqual(['architecture']);

      act(() => {
        result.current.toggleTag('architecture');
      });
      expect(result.current.selectedTags).toEqual([]);
    });
  });

  describe('Community Search State', () => {
    it('should manage community search specific state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.communityUuid).toBe('');
      expect(result.current.includeEpisodes).toBe(true);

      act(() => {
        result.current.setCommunityUuid('community-123');
        result.current.setIncludeEpisodes(false);
      });

      expect(result.current.communityUuid).toBe('community-123');
      expect(result.current.includeEpisodes).toBe(false);
    });
  });

  describe('Search History', () => {
    it('should add to search history', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.searchHistory).toEqual([]);

      act(() => {
        result.current.addToSearchHistory('test query', 'semantic');
      });

      expect(result.current.searchHistory).toHaveLength(1);
      expect(result.current.searchHistory[0]).toEqual({
        query: 'test query',
        mode: 'semantic',
        timestamp: expect.any(Number),
      });
    });

    it('should limit search history to 10 items', () => {
      const { result } = renderHook(() => useSearchState());

      // Add 15 items
      act(() => {
        for (let i = 0; i < 15; i++) {
          result.current.addToSearchHistory(`query ${i}`, 'semantic');
        }
      });

      expect(result.current.searchHistory).toHaveLength(10);
      expect(result.current.searchHistory[0].query).toBe('query 14');
    });

    it('should clear search history', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.addToSearchHistory('test', 'semantic');
      });
      expect(result.current.searchHistory).toHaveLength(1);

      act(() => {
        result.current.clearSearchHistory();
      });
      expect(result.current.searchHistory).toHaveLength(0);
    });
  });

  describe('Subgraph State', () => {
    it('should manage subgraph mode and selected IDs', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.isSubgraphMode).toBe(false);
      expect(result.current.selectedSubgraphIds).toEqual([]);

      act(() => {
        result.current.setSubgraphMode(true);
        result.current.setSelectedSubgraphIds(['uuid-1', 'uuid-2']);
      });

      expect(result.current.isSubgraphMode).toBe(true);
      expect(result.current.selectedSubgraphIds).toEqual(['uuid-1', 'uuid-2']);
    });

    it('should toggle subgraph mode', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.toggleSubgraphMode();
      });

      expect(result.current.isSubgraphMode).toBe(true);

      act(() => {
        result.current.toggleSubgraphMode();
      });

      expect(result.current.isSubgraphMode).toBe(false);
    });
  });

  describe('Voice Search State', () => {
    it('should manage listening state', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.isListening).toBe(false);

      act(() => {
        result.current.setListening(true);
      });

      expect(result.current.isListening).toBe(true);

      act(() => {
        result.current.setListening(false);
      });

      expect(result.current.isListening).toBe(false);
    });
  });

  describe('Mobile Config State', () => {
    it('should manage mobile config panel visibility', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.showMobileConfig).toBe(false);

      act(() => {
        result.current.setShowMobileConfig(true);
      });

      expect(result.current.showMobileConfig).toBe(true);
    });
  });

  describe('Copy ID State', () => {
    it('should set copied ID', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.copiedId).toBe(null);

      act(() => {
        result.current.setCopiedId('uuid-123');
      });

      expect(result.current.copiedId).toBe('uuid-123');
    });

    it('should clear copied ID', () => {
      const { result } = renderHook(() => useSearchState());

      act(() => {
        result.current.setCopiedId('uuid-123');
      });
      expect(result.current.copiedId).toBe('uuid-123');

      act(() => {
        result.current.setCopiedId(null);
      });
      expect(result.current.copiedId).toBe(null);
    });
  });

  describe('Config Tab State', () => {
    it('should manage config tab', () => {
      const { result } = renderHook(() => useSearchState());

      expect(result.current.configTab).toBe('params');

      act(() => {
        result.current.setConfigTab('filters');
      });

      expect(result.current.configTab).toBe('filters');

      act(() => {
        result.current.setConfigTab('params');
      });

      expect(result.current.configTab).toBe('params');
    });
  });
});
