/**
 * EnhancedSearch - Semantic and Graph-based Search
 *
 * ## Usage
 *
 * ### Convenience Usage (Default rendering)
 * ```tsx
 * <EnhancedSearch />
 * ```
 *
 * ### Compound Components (Custom rendering)
 * ```tsx
 * <EnhancedSearch>
 *   <EnhancedSearch.Form />
 *   <EnhancedSearch.Config />
 *   <EnhancedSearch.Results />
 *   <EnhancedSearch.Graph />
 * </EnhancedSearch>
 * ```
 *
 * ### Namespace Usage
 * ```tsx
 * <EnhancedSearch.Root>
 *   <EnhancedSearch.Form />
 *   <EnhancedSearch.Graph />
 * </EnhancedSearch.Root>
 * ```
 */

import React, { useState, useMemo, useCallback, useRef, useEffect, Children, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { AlertCircle, Maximize, Network } from 'lucide-react';

import { CytoscapeGraph } from '@/components/graph/CytoscapeGraph';

import { graphService } from '../../services/graphService';
import { useProjectStore } from '../../stores/project';

import { SearchForm, SearchResults, SearchConfig } from './search';

import type { SearchMode, SearchResult } from './search';
import type {
  EnhancedSearchRootProps,
  EnhancedSearchFormProps,
  EnhancedSearchConfigProps,
  EnhancedSearchResultsProps,
  EnhancedSearchGraphProps,
  EnhancedSearchErrorProps,
  EnhancedSearchHistoryProps,
  EnhancedSearchCompound,
} from './search/types';

// Local Web Speech API subset used by this page.
interface SpeechRecognitionResultLike {
  transcript: string;
}

interface SpeechRecognitionAlternativeListLike {
  [index: number]: SpeechRecognitionResultLike | undefined;
}

interface SpeechRecognitionResultListLike {
  [index: number]: SpeechRecognitionAlternativeListLike | undefined;
}

interface SpeechRecognitionEventLike {
  results: SpeechRecognitionResultListLike;
}

interface SpeechRecognitionLike {
  onstart: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
}

interface SpeechRecognitionConstructorLike {
  new (): SpeechRecognitionLike;
}

// Use refs for values that change frequently but don't need to trigger re-renders
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
  customTimeRange: { since?: string | undefined; until?: string | undefined };
  projectId: string | undefined;
}

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const FORM_SYMBOL = Symbol('EnhancedSearchForm');
const CONFIG_SYMBOL = Symbol('EnhancedSearchConfig');
const RESULTS_SYMBOL = Symbol('EnhancedSearchResults');
const GRAPH_SYMBOL = Symbol('EnhancedSearchGraph');
const ERROR_SYMBOL = Symbol('EnhancedSearchError');
const HISTORY_SYMBOL = Symbol('EnhancedSearchHistory');

// ========================================
// Sub-Components (Marker Components)
// ========================================
// Must be defined before the main component to avoid initialization issues

function FormMarker(_props: EnhancedSearchFormProps) {
  return null;
}
function ConfigMarker(_props: EnhancedSearchConfigProps) {
  return null;
}
function ResultsMarker(_props: EnhancedSearchResultsProps) {
  return null;
}
function GraphMarker(_props: EnhancedSearchGraphProps) {
  return null;
}
function ErrorMarker(_props: EnhancedSearchErrorProps) {
  return null;
}
function HistoryMarker(_props: EnhancedSearchHistoryProps) {
  return null;
}

function markComponent<P>(component: React.FC<P>, marker: symbol, displayName: string): void {
  const marked = component as React.FC<P> &
    Record<symbol, unknown> & {
      displayName?: string | undefined;
    };
  marked[marker] = true;
  marked.displayName = displayName;
}

function hasMarker<P>(child: React.ReactNode, marker: symbol): child is React.ReactElement<P> {
  if (!React.isValidElement(child)) {
    return false;
  }

  const elementType = child.type as unknown;
  if (
    typeof elementType !== 'function' &&
    (typeof elementType !== 'object' || elementType === null)
  ) {
    return false;
  }

  return (elementType as Record<symbol, unknown>)[marker] === true;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function getStringField(record: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string') {
      return value;
    }
  }
  return undefined;
}

function getNumberField(record: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number') {
      return value;
    }
  }
  return undefined;
}

function getStringArrayField(
  record: Record<string, unknown>,
  ...keys: string[]
): string[] | undefined {
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value) && value.every((item): item is string => typeof item === 'string')) {
      return value;
    }
  }
  return undefined;
}

function toSearchResult(item: unknown, fallbackContent: string): SearchResult {
  const record = isRecord(item) ? item : {};
  const metadata = isRecord(record.metadata) ? record.metadata : {};

  const content =
    getStringField(record, 'content', 'summary', 'text') ??
    getStringField(metadata, 'content', 'summary', 'text') ??
    fallbackContent;
  const uuid = getStringField(record, 'uuid') ?? getStringField(metadata, 'uuid');
  const name = getStringField(record, 'name') ?? getStringField(metadata, 'name');
  const createdAt = getStringField(record, 'created_at') ?? getStringField(metadata, 'created_at');
  const tags = getStringArrayField(record, 'tags') ?? getStringArrayField(metadata, 'tags') ?? [];

  return {
    content,
    score: getNumberField(record, 'score') ?? 0,
    metadata: {
      ...metadata,
      type: getStringField(record, 'type', 'entity_type') ?? 'Result',
      uuid,
      name,
      depth: getNumberField(record, 'depth'),
      created_at: createdAt,
      tags,
    },
    source: getStringField(record, 'source') ?? 'unknown',
  };
}

// Attach symbols after function declarations
markComponent(FormMarker, FORM_SYMBOL, 'EnhancedSearchForm');
markComponent(ConfigMarker, CONFIG_SYMBOL, 'EnhancedSearchConfig');
markComponent(ResultsMarker, RESULTS_SYMBOL, 'EnhancedSearchResults');
markComponent(GraphMarker, GRAPH_SYMBOL, 'EnhancedSearchGraph');
markComponent(ErrorMarker, ERROR_SYMBOL, 'EnhancedSearchError');
markComponent(HistoryMarker, HISTORY_SYMBOL, 'EnhancedSearchHistory');

// ========================================
// Main Component
// ========================================

const EnhancedSearchInner: React.FC<EnhancedSearchRootProps> = memo(
  ({
    projectId: propProjectId,
    tenantId: propTenantId,
    children,
    defaultSearchMode = 'semantic',
    defaultViewMode = 'grid',
    defaultConfigOpen = true,
  }) => {
    const { t } = useTranslation();
    const { projectId: routeProjectId } = useParams();
    const { currentProject } = useProjectStore();

    const projectId = propProjectId || routeProjectId;
    const tenantId = propTenantId || currentProject?.tenant_id;

    // Parse children to detect sub-components
    const childrenArray = Children.toArray(children);
    const formChild = childrenArray.find(
      (child): child is React.ReactElement<EnhancedSearchFormProps> =>
        hasMarker<EnhancedSearchFormProps>(child, FORM_SYMBOL)
    );
    const configChild = childrenArray.find(
      (child): child is React.ReactElement<EnhancedSearchConfigProps> =>
        hasMarker<EnhancedSearchConfigProps>(child, CONFIG_SYMBOL)
    );
    const resultsChild = childrenArray.find(
      (child): child is React.ReactElement<EnhancedSearchResultsProps> =>
        hasMarker<EnhancedSearchResultsProps>(child, RESULTS_SYMBOL)
    );
    const graphChild = childrenArray.find(
      (child): child is React.ReactElement<EnhancedSearchGraphProps> =>
        hasMarker<EnhancedSearchGraphProps>(child, GRAPH_SYMBOL)
    );
    const errorChild = childrenArray.find(
      (child): child is React.ReactElement<EnhancedSearchErrorProps> =>
        hasMarker<EnhancedSearchErrorProps>(child, ERROR_SYMBOL)
    );
    const historyChild = childrenArray.find(
      (child): child is React.ReactElement<EnhancedSearchHistoryProps> =>
        hasMarker<EnhancedSearchHistoryProps>(child, HISTORY_SYMBOL)
    );

    // Determine if using compound mode
    const hasSubComponents = Boolean(
      formChild || configChild || resultsChild || graphChild || errorChild || historyChild
    );

    // In legacy mode, include all sections by default
    // In compound mode, only include explicitly specified sections
    const includeForm = hasSubComponents ? !!formChild : true;
    const includeConfig = hasSubComponents ? !!configChild : true;
    const includeResults = hasSubComponents ? !!resultsChild : true;
    const includeGraph = hasSubComponents ? !!graphChild : true;
    const includeError = hasSubComponents ? !!errorChild : true;
    const includeHistory = hasSubComponents ? !!historyChild : true;

    // State
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<SearchResult[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isSearchFocused, setIsSearchFocused] = useState(false);

    // Search Mode
    const [searchMode, setSearchMode] = useState<SearchMode>(defaultSearchMode);

    // Configuration State
    const [retrievalMode, setRetrievalMode] = useState<'hybrid' | 'nodeDistance'>('hybrid');
    const [strategy, setStrategy] = useState('COMBINED_HYBRID_SEARCH_RRF');
    const [focalNode, setFocalNode] = useState('');
    const [crossEncoder, setCrossEncoder] = useState('bge');
    const [timeRange, setTimeRange] = useState('last30');
    const [customTimeRange, setCustomTimeRange] = useState<{
      since?: string | undefined;
      until?: string | undefined;
    }>({});
    const [configTab, setConfigTab] = useState<'params' | 'filters'>('params');
    const [showMobileConfig, setShowMobileConfig] = useState(false);
    const [isConfigOpen, setIsConfigOpen] = useState(defaultConfigOpen);
    const [isResultsCollapsed, setIsResultsCollapsed] = useState(false);
    const [viewMode, setViewMode] = useState<'grid' | 'list'>(defaultViewMode);
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

    // Ref to store current search params
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

    // Optimized handleSearch
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
        let data: { results: unknown[] };

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
              focal_node_uuid:
                params.retrievalMode === 'nodeDistance' ? params.focalNode : undefined,
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
        const mappedResults = data.results.map((item) =>
          toSearchResult(item, t('project.search.results.no_content'))
        );

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
          const firstUuid = mappedResults[0]?.metadata.uuid;
          if (firstUuid) {
            setSelectedSubgraphIds([firstUuid]);
          }
        }
      } catch (err) {
        console.error('Search failed:', err);
        setError(t('project.search.errors.search_failed'));
      } finally {
        setLoading(false);
      }
    }, [t]);

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

      const speechWindow = window as unknown as {
        SpeechRecognition?: SpeechRecognitionConstructorLike | undefined;
        webkitSpeechRecognition?: SpeechRecognitionConstructorLike | undefined;
      };
      const SpeechRecognition =
        speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
      if (!SpeechRecognition) {
        setError(t('project.search.errors.voice_not_supported'));
        return;
      }

      const recognition = new SpeechRecognition();

      recognition.onstart = () => {
        setIsListening(true);
      };

      recognition.onresult = (event: SpeechRecognitionEventLike) => {
        const transcript = event.results[0]?.[0]?.transcript;
        if (transcript) {
          setQuery(transcript);
        }
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
      a.download = `search-results-${String(Date.now())}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, [results]);

    const handleCopyId = useCallback((id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      void navigator.clipboard.writeText(id);
      setCopiedId(id);
      setTimeout(() => {
        setCopiedId(null);
      }, 2000);
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
      <div className="flex h-full min-w-0 overflow-hidden bg-slate-50 font-sans text-slate-900 dark:bg-[#121520] dark:text-white">
        <main className="flex min-w-0 flex-1 flex-col bg-slate-50 dark:bg-[#121520]">
          {/* Search Form */}
          {includeForm && (
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
              onSearch={() => {
                void handleSearch();
              }}
              onVoiceSearch={handleVoiceSearch}
              onConfigToggle={() => {
                setIsConfigOpen(!isConfigOpen);
              }}
              onHistoryToggle={() => {
                setShowHistory(!showHistory);
              }}
              onHistoryItemClick={(item) => {
                setQuery(item.query);
                setSearchMode(item.mode as SearchMode);
                setShowHistory(false);
              }}
              onExportResults={handleExportResults}
              canExportResults={results.length > 0}
            />
          )}

          <div className="flex min-w-0 flex-1 gap-4 overflow-hidden p-4 pt-2 sm:gap-6 sm:p-6">
            {/* Config Sidebar */}
            {includeConfig && (
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
                onMobileConfigClose={() => {
                  setShowMobileConfig(false);
                }}
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
            )}

            <div className="flex min-w-0 flex-1 flex-col gap-4 overflow-hidden">
              {/* Error Message */}
              {includeError && error && (
                <div
                  className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 flex items-center gap-2"
                  data-testid="search-error"
                >
                  <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                  <span className="text-sm text-red-800 dark:text-red-400">{error}</span>
                </div>
              )}

              {/* Graph View */}
              {includeGraph && (
                <section
                  className={`
                min-w-0 bg-white dark:bg-[#1e212b] rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 relative overflow-hidden group transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 ease-in-out
                ${isResultsCollapsed ? 'flex-1' : 'h-[55%]'}
              `}
                >
                  <div className="absolute top-4 left-4 z-10 flex gap-2">
                    <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm p-1 flex gap-1">
                      <button
                        onClick={() => {
                          setIsResultsCollapsed(!isResultsCollapsed);
                        }}
                        className={`p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded text-slate-600 dark:text-slate-400 transition-colors ${isResultsCollapsed ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20' : ''}`}
                        title={isResultsCollapsed ? 'Show Results' : 'Expand Graph'}
                      >
                        <Maximize className="w-4 h-4" />
                      </button>
                      {highlightNodeIds.length > 0 && (
                        <button
                          onClick={() => {
                            setIsSubgraphMode(!isSubgraphMode);
                          }}
                          className={`p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded text-slate-600 dark:text-slate-400 transition-colors ${isSubgraphMode ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20' : ''}`}
                          title={isSubgraphMode ? 'Show Full Graph' : 'Show Result Subgraph'}
                        >
                          <Network className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Real Graph Visualization */}
                  <div className="relative h-full w-full min-w-0 overflow-hidden">
                    <CytoscapeGraph
                      projectId={projectId}
                      tenantId={tenantId}
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
              )}

              {/* Results List */}
              {includeResults && (
                <SearchResults
                  results={results}
                  loading={loading}
                  isResultsCollapsed={isResultsCollapsed}
                  viewMode={viewMode}
                  copiedId={copiedId}
                  selectedSubgraphIds={selectedSubgraphIds}
                  onResultsCollapseToggle={() => {
                    setIsResultsCollapsed(!isResultsCollapsed);
                  }}
                  onViewModeChange={setViewMode}
                  onResultClick={handleResultClick}
                  onCopyId={handleCopyId}
                />
              )}

              {/* Search History */}
              {includeHistory && (
                <div
                  className="bg-white dark:bg-slate-800 rounded-lg shadow-sm border border-slate-200 dark:border-slate-700 p-4"
                  data-testid="search-history"
                >
                  <h3 className="text-sm font-medium mb-2">
                    {t('project.search.actions.searchHistory', 'Search History')}
                  </h3>
                  {searchHistory.length > 0 ? (
                    <ul className="space-y-1">
                      {searchHistory.map((item, index) => (
                        <li
                          key={index}
                          className="text-xs text-slate-600 dark:text-slate-400 cursor-pointer hover:text-slate-900 dark:hover:text-white"
                          onClick={() => {
                            setQuery(item.query);
                            setSearchMode(item.mode as SearchMode);
                            setShowHistory(false);
                          }}
                        >
                          {item.query} ({item.mode})
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-slate-500 dark:text-slate-500">
                      {t('project.search.actions.noHistory', 'No search history')}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    );
  }
);

// Create compound component with sub-components
const EnhancedSearchMemo = memo(EnhancedSearchInner);
EnhancedSearchMemo.displayName = 'EnhancedSearch';

// Create compound component object
const EnhancedSearchCompound = EnhancedSearchMemo as unknown as EnhancedSearchCompound;
EnhancedSearchCompound.Form = FormMarker;
EnhancedSearchCompound.Config = ConfigMarker;
EnhancedSearchCompound.Results = ResultsMarker;
EnhancedSearchCompound.Graph = GraphMarker;
EnhancedSearchCompound.Error = ErrorMarker;
EnhancedSearchCompound.History = HistoryMarker;
EnhancedSearchCompound.Root = EnhancedSearchMemo;

// Export compound component
export const EnhancedSearch = EnhancedSearchCompound;

export default EnhancedSearch;
