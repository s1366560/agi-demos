/**
 * EnhancedSearch - Semantic and Graph-based Search
 *
 * Refactored to use sub-components for better performance and maintainability.
 */

import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { AlertCircle, Maximize, Network } from 'lucide-react';

import { CytoscapeGraph } from '@/components/graph/CytoscapeGraph';

import { graphService } from '../../services/graphService';
import { useProjectStore } from '../../stores/project';

import { SearchForm, SearchResults, SearchConfig } from './search';

import type { SearchMode, SearchResult } from './search';

// Type declarations for Web Speech API
declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

// Use refs for values that change frequently but don't need to trigger re-renders
// This helps reduce useCallback dependencies
interface SearchParamsRef {
  searchMode: SearchMode;
  query: string;
  startEntityUuid: string;
  communityUuid: string;
  retrievalMode: 'hybrid' | 'nodeDistance';
  strategy: string;
  focalNode: string;
  crossEncoder: string;
  maxDepth: number;
  relationshipTypes: string[];
  selectedEntityTypes: string[];
  selectedTags: string[];
  includeEpisodes: boolean;
  timeRange: string;
  customTimeRange: { since?: string; until?: string };
  projectId: string | undefined;
}

export const EnhancedSearch: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const { currentProject } = useProjectStore();

  // State
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSearchFocused, setIsSearchFocused] = useState(false);

  // Search Mode
  const [searchMode, setSearchMode] = useState<SearchMode>('semantic');

  // Configuration State
  const [retrievalMode, setRetrievalMode] = useState<'hybrid' | 'nodeDistance'>('hybrid');
  const [strategy, setStrategy] = useState('COMBINED_HYBRID_SEARCH_RRF');
  const [focalNode, setFocalNode] = useState('');
  const [crossEncoder, setCrossEncoder] = useState('bge');
  const [timeRange, setTimeRange] = useState('last30');
  const [customTimeRange, setCustomTimeRange] = useState<{ since?: string; until?: string }>({});
  const [configTab, setConfigTab] = useState<'params' | 'filters'>('params');
  const [showMobileConfig, setShowMobileConfig] = useState(false);
  const [isConfigOpen, setIsConfigOpen] = useState(true);
  const [isResultsCollapsed, setIsResultsCollapsed] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isSubgraphMode, setIsSubgraphMode] = useState(false);
  const [selectedSubgraphIds, setSelectedSubgraphIds] = useState<string[]>([]);

  // Graph Traversal State
  const [startEntityUuid, setStartEntityUuid] = useState('');
  const [maxDepth, setMaxDepth] = useState(2);
  const [relationshipTypes, setRelationshipTypes] = useState<string[]>([]);

  // Faceted Search State
  const [selectedEntityTypes, setSelectedEntityTypes] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [availableTags] = useState<string[]>(['architecture', 'meeting', 'decisions', 'Q3']);

  // Community Search State
  const [communityUuid, setCommunityUuid] = useState('');
  const [includeEpisodes, setIncludeEpisodes] = useState(true);

  // Voice Search State
  const [isListening, setIsListening] = useState(false);

  // Search History
  const [searchHistory, setSearchHistory] = useState<
    Array<{ query: string; mode: string; timestamp: number }>
  >([]);
  const [showHistory, setShowHistory] = useState(false);

  // Help Tooltip State
  const [showTooltip, setShowTooltip] = useState<string | null>(null);

  // Ref to store current search params - this avoids including all state in useCallback dependencies
  const searchParamsRef = useRef<SearchParamsRef>({
    searchMode,
    query,
    startEntityUuid,
    communityUuid,
    retrievalMode,
    strategy,
    focalNode,
    crossEncoder,
    maxDepth,
    relationshipTypes,
    selectedEntityTypes,
    selectedTags,
    includeEpisodes,
    timeRange,
    customTimeRange,
    projectId,
  });

  // Update ref whenever params change
  useEffect(() => {
    searchParamsRef.current = {
      searchMode,
      query,
      startEntityUuid,
      communityUuid,
      retrievalMode,
      strategy,
      focalNode,
      crossEncoder,
      maxDepth,
      relationshipTypes,
      selectedEntityTypes,
      selectedTags,
      includeEpisodes,
      timeRange,
      customTimeRange,
      projectId,
    };
  }, [
    searchMode,
    query,
    startEntityUuid,
    communityUuid,
    retrievalMode,
    strategy,
    focalNode,
    crossEncoder,
    maxDepth,
    relationshipTypes,
    selectedEntityTypes,
    selectedTags,
    includeEpisodes,
    timeRange,
    customTimeRange,
    projectId,
  ]);

  // Optimized handleSearch with minimal dependencies (only stable refs/setters)
  const handleSearch = useCallback(async () => {
    const params = searchParamsRef.current;

    // Validate based on search mode
    if (params.searchMode === 'graphTraversal' && !params.startEntityUuid) {
      setError(t('project.search.errors.enter_start_uuid'));
      return;
    }
    if (params.searchMode === 'community' && !params.communityUuid) {
      setError(t('project.search.errors.enter_community_uuid'));
      return;
    }
    if (
      (params.searchMode === 'semantic' ||
        params.searchMode === 'temporal' ||
        params.searchMode === 'faceted') &&
      !params.query
    ) {
      setError(t('project.search.errors.enter_query'));
      return;
    }

    setLoading(true);
    setError(null);

    try {
      let data: any;

      switch (params.searchMode) {
        case 'semantic': {
          let since = undefined;
          if (params.timeRange === 'last30') {
            const date = new Date();
            date.setDate(date.getDate() - 30);
            since = date.toISOString();
          } else if (params.timeRange === 'custom' && params.customTimeRange.since) {
            since = params.customTimeRange.since;
          }

          data = await graphService.advancedSearch({
            query: params.query,
            strategy: params.strategy,
            project_id: params.projectId,
            focal_node_uuid: params.retrievalMode === 'nodeDistance' ? params.focalNode : undefined,
            reranker: params.crossEncoder,
            since,
          });
          break;
        }

        case 'graphTraversal':
          data = await graphService.searchByGraphTraversal({
            start_entity_uuid: params.startEntityUuid,
            max_depth: params.maxDepth,
            relationship_types:
              params.relationshipTypes.length > 0 ? params.relationshipTypes : undefined,
            limit: 50,
          });
          break;

        case 'temporal':
          data = await graphService.searchTemporal({
            query: params.query,
            since: params.timeRange === 'custom' ? params.customTimeRange.since : undefined,
            until: params.timeRange === 'custom' ? params.customTimeRange.until : undefined,
            limit: 50,
          });
          break;

        case 'faceted':
          data = await graphService.searchWithFacets({
            query: params.query,
            entity_types:
              params.selectedEntityTypes.length > 0 ? params.selectedEntityTypes : undefined,
            tags: params.selectedTags.length > 0 ? params.selectedTags : undefined,
            since: params.timeRange === 'custom' ? params.customTimeRange.since : undefined,
            limit: 50,
          });
          break;

        case 'community':
          data = await graphService.searchByCommunity({
            community_uuid: params.communityUuid,
            limit: 50,
            include_episodes: params.includeEpisodes,
          });
          break;
      }

      // Map the raw results to our display format
      const mappedResults = (data.results || []).map((item: any) => ({
        content:
          item.content || item.summary || item.text || t('project.search.results.no_content'),
        score: item.score || 0,
        metadata: {
          ...item.metadata,
          type: item.type || item.entity_type || 'Result',
          uuid: item.uuid || item.metadata?.uuid,
          name: item.name || item.metadata?.name,
          depth: item.depth,
          created_at: item.created_at || item.metadata?.created_at,
          tags: item.tags || item.metadata?.tags || [],
        },
        source: item.source || 'unknown',
      }));

      setResults(mappedResults);

      // Add to search history
      if (params.query || params.startEntityUuid || params.communityUuid) {
        const historyItem = {
          query: params.query || params.startEntityUuid || params.communityUuid || '',
          mode: params.searchMode,
          timestamp: Date.now(),
        };
        setSearchHistory((prev) => [historyItem, ...prev.slice(0, 9)]);
      }

      // Expand results by default when search is done
      if (mappedResults.length > 0) {
        setIsResultsCollapsed(false);
        setIsSubgraphMode(true);
        if (mappedResults[0].metadata.uuid) {
          setSelectedSubgraphIds([mappedResults[0].metadata.uuid]);
        }
      }
    } catch (err) {
      console.error('Search failed:', err);
      setError(t('project.search.errors.search_failed'));
    } finally {
      setLoading(false);
    }
  }, [t]); // Only depends on translation function

  // Extract node IDs for graph highlighting
  const highlightNodeIds = useMemo(() => {
    const ids = new Set<string>();
    results.forEach((result) => {
      if (result.metadata.uuid) {
        ids.add(result.metadata.uuid);
      }
    });
    return Array.from(ids);
  }, [results]);

  // Voice Search Handler
  const handleVoiceSearch = useCallback(() => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      setError(t('project.search.errors.voice_not_supported'));
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setQuery(transcript);
      setIsListening(false);
    };

    recognition.onerror = () => {
      setIsListening(false);
      setError(t('project.search.errors.voice_failed'));
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognition.start();
  }, [t]);

  // Export Results Handler
  const handleExportResults = useCallback(() => {
    const params = searchParamsRef.current;
    const exportData = {
      search_mode: params.searchMode,
      query: params.query || params.startEntityUuid || params.communityUuid,
      timestamp: new Date().toISOString(),
      total_results: results.length,
      results: results.map((r) => ({
        content: r.content,
        score: r.score,
        type: r.metadata.type,
        uuid: r.metadata.uuid,
        name: r.metadata.name,
        created_at: r.metadata.created_at,
      })),
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `search-results-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [results]);

  const handleCopyId = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }, []);

  const handleResultClick = useCallback((result: SearchResult) => {
    if (result.metadata.uuid) {
      setSelectedSubgraphIds([result.metadata.uuid]);
      setIsSubgraphMode(true);
    }
  }, []);

  // Reset subgraph mode when no results
  useEffect(() => {
    if (highlightNodeIds.length === 0) {
      setIsSubgraphMode(false);
    }
  }, [highlightNodeIds]);

  return (
    <div className="bg-slate-50 dark:bg-[#121520] text-slate-900 dark:text-white font-sans h-full flex overflow-hidden">
      <main className="flex-1 flex flex-col min-w-0 bg-slate-50 dark:bg-[#121520]">
        {/* Search Form */}
        <SearchForm
          searchMode={searchMode}
          query={query}
          startEntityUuid={startEntityUuid}
          communityUuid={communityUuid}
          isSearchFocused={isSearchFocused}
          isListening={isListening}
          loading={loading}
          isConfigOpen={isConfigOpen}
          searchHistory={searchHistory}
          showHistory={showHistory}
          onSearchModeChange={setSearchMode}
          onQueryChange={setQuery}
          onStartEntityUuidChange={setStartEntityUuid}
          onCommunityUuidChange={setCommunityUuid}
          onSearchFocusChange={setIsSearchFocused}
          onSearch={handleSearch}
          onVoiceSearch={handleVoiceSearch}
          onConfigToggle={() => setIsConfigOpen(!isConfigOpen)}
          onHistoryToggle={() => setShowHistory(!showHistory)}
          onHistoryItemClick={(item) => {
            setQuery(item.query);
            setSearchMode(item.mode as SearchMode);
            setShowHistory(false);
          }}
          onExportResults={handleExportResults}
        />

        <div className="flex-1 flex overflow-hidden p-6 gap-6 pt-2">
          {/* Config Sidebar */}
          <SearchConfig
            searchMode={searchMode}
            configTab={configTab}
            isConfigOpen={isConfigOpen}
            showMobileConfig={showMobileConfig}
            retrievalMode={retrievalMode}
            strategy={strategy}
            focalNode={focalNode}
            crossEncoder={crossEncoder}
            maxDepth={maxDepth}
            relationshipTypes={relationshipTypes}
            timeRange={timeRange}
            customTimeRange={customTimeRange}
            selectedEntityTypes={selectedEntityTypes}
            selectedTags={selectedTags}
            availableTags={availableTags}
            communityUuid={communityUuid}
            includeEpisodes={includeEpisodes}
            onMobileConfigClose={() => setShowMobileConfig(false)}
            onConfigTabChange={setConfigTab}
            onRetrievalModeChange={setRetrievalMode}
            onStrategyChange={setStrategy}
            onFocalNodeChange={setFocalNode}
            onCrossEncoderChange={setCrossEncoder}
            onMaxDepthChange={setMaxDepth}
            onRelationshipTypesChange={setRelationshipTypes}
            onTimeRangeChange={setTimeRange}
            onCustomTimeRangeChange={setCustomTimeRange}
            onSelectedEntityTypesChange={setSelectedEntityTypes}
            onSelectedTagsChange={setSelectedTags}
            onIncludeEpisodesChange={setIncludeEpisodes}
            showTooltip={showTooltip}
            onShowTooltip={setShowTooltip}
          />

          <div className="flex-1 flex flex-col gap-4 min-w-0 overflow-hidden">
            {/* Error Message */}
            {error && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 flex items-center gap-2">
                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                <span className="text-sm text-red-800 dark:text-red-400">{error}</span>
              </div>
            )}

            {/* Graph View */}
            <section
              className={`
                            bg-white dark:bg-[#1e212b] rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 relative overflow-hidden group transition-all duration-300 ease-in-out
                            ${isResultsCollapsed ? 'flex-1' : 'h-[55%]'}
                        `}
            >
              <div className="absolute top-4 left-4 z-10 flex gap-2">
                <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm p-1 flex gap-1">
                  <button
                    onClick={() => setIsResultsCollapsed(!isResultsCollapsed)}
                    className={`p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded text-slate-600 dark:text-slate-400 transition-colors ${isResultsCollapsed ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20' : ''}`}
                    title={isResultsCollapsed ? 'Show Results' : 'Expand Graph'}
                  >
                    <Maximize className="w-4 h-4" />
                  </button>
                  {highlightNodeIds.length > 0 && (
                    <button
                      onClick={() => setIsSubgraphMode(!isSubgraphMode)}
                      className={`p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded text-slate-600 dark:text-slate-400 transition-colors ${isSubgraphMode ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20' : ''}`}
                      title={isSubgraphMode ? 'Show Full Graph' : 'Show Result Subgraph'}
                    >
                      <Network className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>

              {/* Real Graph Visualization */}
              <div className="w-full h-full relative">
                <CytoscapeGraph
                  projectId={projectId}
                  tenantId={currentProject?.tenant_id}
                  highlightNodeIds={highlightNodeIds}
                  subgraphNodeIds={isSubgraphMode ? selectedSubgraphIds : undefined}
                  includeCommunities={true}
                  onNodeClick={(node) => {
                    if (node?.uuid) {
                      setFocalNode(node.uuid);
                      setRetrievalMode('nodeDistance');
                    }
                  }}
                />
              </div>
            </section>

            {/* Results List */}
            <SearchResults
              results={results}
              loading={loading}
              isResultsCollapsed={isResultsCollapsed}
              viewMode={viewMode}
              copiedId={copiedId}
              selectedSubgraphIds={selectedSubgraphIds}
              onResultsCollapseToggle={() => setIsResultsCollapsed(!isResultsCollapsed)}
              onViewModeChange={setViewMode}
              onResultClick={handleResultClick}
              onCopyId={handleCopyId}
              onSubgraphModeToggle={() => setIsSubgraphMode(!isSubgraphMode)}
            />
          </div>
        </div>
      </main>
    </div>
  );
};
