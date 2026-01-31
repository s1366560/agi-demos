/**
 * useSearchState - Custom hook for EnhancedSearch state management
 *
 * Extracts state management logic from EnhancedSearch component
 * following React composition patterns.
 *
 * This hook manages all the state for the EnhancedSearch component,
 * including search modes, filters, results, and UI state.
 */

import { useState, useMemo, useCallback } from 'react'

export type SearchMode = 'semantic' | 'graphTraversal' | 'temporal' | 'faceted' | 'community'
export type RetrievalMode = 'hybrid' | 'nodeDistance'
export type ViewMode = 'grid' | 'list'
export type ConfigTab = 'params' | 'filters'
export type TimeRange = 'all' | 'last30' | 'custom'

export interface SearchResult {
  content: string
  score: number
  metadata: {
    type: string
    name?: string
    uuid?: string
    depth?: number
    created_at?: string
    tags?: string[]
    [key: string]: unknown
  }
  source: string
}

export interface SearchHistoryItem {
  query: string
  mode: string
  timestamp: number
}

export interface CustomTimeRange {
  since?: string
  until?: string
}

/**
 * Custom hook to manage all EnhancedSearch state
 *
 * @returns Object containing all state values and setter functions
 */
export function useSearchState() {
  // Basic search state
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searchMode, setSearchMode] = useState<SearchMode>('semantic')

  // UI state
  const [isConfigOpen, setIsConfigOpen] = useState(true)
  const [isResultsCollapsed, setIsResultsCollapsedState] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [configTab, setConfigTab] = useState<ConfigTab>('params')
  const [showMobileConfig, setShowMobileConfig] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // Semantic search state
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>('hybrid')
  const [strategy, setStrategy] = useState('COMBINED_HYBRID_SEARCH_RRF')
  const [focalNode, setFocalNode] = useState('')
  const [crossEncoder, setCrossEncoder] = useState('bge')

  // Graph traversal state
  const [startEntityUuid, setStartEntityUuid] = useState('')
  const [maxDepth, setMaxDepthState] = useState(2)
  const [relationshipTypes, setRelationshipTypes] = useState<string[]>([])

  // Temporal search state
  const [timeRange, setTimeRange] = useState<TimeRange>('last30')
  const [customTimeRange, setCustomTimeRange] = useState<CustomTimeRange>({})

  // Faceted search state
  const [selectedEntityTypes, setSelectedEntityTypesState] = useState<string[]>([])
  const [selectedTags, setSelectedTagsState] = useState<string[]>([])
  const availableTags = ['architecture', 'meeting', 'decisions', 'Q3']

  // Community search state
  const [communityUuid, setCommunityUuid] = useState('')
  const [includeEpisodes, setIncludeEpisodes] = useState(true)

  // Graph/subgraph state
  const [isSubgraphMode, setIsSubgraphModeState] = useState(false)
  const [selectedSubgraphIds, setSelectedSubgraphIdsState] = useState<string[]>([])

  // Voice search state
  const [isListening, setListening] = useState(false)

  // Search history state
  const [searchHistory, setSearchHistoryState] = useState<SearchHistoryItem[]>([])

  // Memoized highlight node IDs from results
  const highlightNodeIds = useMemo(() => {
    const ids = new Set<string>()
    results.forEach(result => {
      if (result.metadata.uuid) {
        ids.add(result.metadata.uuid)
      }
    })
    return Array.from(ids)
  }, [results])

  // Wrapper functions with additional logic
  const toggleResultsCollapse = useCallback(() => {
    setIsResultsCollapsedState(prev => !prev)
  }, [])

  const toggleConfigOpen = useCallback(() => {
    setIsConfigOpen(prev => !prev)
  }, [])

  const toggleSubgraphMode = useCallback(() => {
    setIsSubgraphModeState(prev => !prev)
  }, [])

  const setMaxDepth = useCallback((value: number) => {
    // Clamp between 1 and 5
    const clamped = Math.max(1, Math.min(5, value))
    setMaxDepthState(clamped)
  }, [])

  const toggleEntityType = useCallback((type: string) => {
    setSelectedEntityTypesState(prev =>
      prev.includes(type)
        ? prev.filter(t => t !== type)
        : [...prev, type]
    )
  }, [])

  const toggleTag = useCallback((tag: string) => {
    setSelectedTagsState(prev =>
      prev.includes(tag)
        ? prev.filter(t => t !== tag)
        : [...prev, tag]
    )
  }, [])

  const addToSearchHistory = useCallback((queryStr: string, mode: SearchMode) => {
    setSearchHistoryState(prev => {
      const newItem: SearchHistoryItem = {
        query: queryStr,
        mode,
        timestamp: Date.now(),
      }
      // Keep last 10 items
      return [newItem, ...prev.slice(0, 9)]
    })
  }, [])

  const clearSearchHistory = useCallback(() => {
    setSearchHistoryState([])
  }, [])

  const setSelectedSubgraphIds = useCallback((ids: string[] | ((prev: string[]) => string[])) => {
    setSelectedSubgraphIdsState(prev => {
      const newIds = typeof ids === 'function' ? ids(prev) : ids
      // Auto-enable subgraph mode if IDs are set
      if (newIds.length > 0 && prev.length === 0) {
        setIsSubgraphModeState(true)
      }
      return newIds
    })
  }, [])

  return {
    // Basic search state
    query,
    setQuery,
    results,
    setResults,
    loading,
    setLoading,
    error,
    setError,
    searchMode,
    setSearchMode,

    // UI state
    isConfigOpen,
    toggleConfigOpen,
    isResultsCollapsed,
    toggleResultsCollapse,
    viewMode,
    setViewMode,
    configTab,
    setConfigTab,
    showMobileConfig,
    setShowMobileConfig,
    copiedId,
    setCopiedId,

    // Semantic search state
    retrievalMode,
    setRetrievalMode,
    strategy,
    setStrategy,
    focalNode,
    setFocalNode,
    crossEncoder,
    setCrossEncoder,

    // Graph traversal state
    startEntityUuid,
    setStartEntityUuid,
    maxDepth,
    setMaxDepth,
    relationshipTypes,
    setRelationshipTypes,

    // Temporal search state
    timeRange,
    setTimeRange,
    customTimeRange,
    setCustomTimeRange,

    // Faceted search state
    selectedEntityTypes,
    setSelectedEntityTypes: setSelectedEntityTypesState,
    toggleEntityType,
    selectedTags,
    setSelectedTags: setSelectedTagsState,
    toggleTag,
    availableTags,

    // Community search state
    communityUuid,
    setCommunityUuid,
    includeEpisodes,
    setIncludeEpisodes,

    // Graph/subgraph state
    isSubgraphMode,
    setIsSubgraphMode: setIsSubgraphModeState,
    setSubgraphMode: setIsSubgraphModeState,
    toggleSubgraphMode,
    selectedSubgraphIds,
    setSelectedSubgraphIds,
    highlightNodeIds,

    // Voice search state
    isListening,
    setListening,

    // Search history state
    searchHistory,
    addToSearchHistory,
    clearSearchHistory,
  }
}

export default useSearchState
