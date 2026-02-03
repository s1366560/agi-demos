/**
 * EnhancedSearch Compound Component Types
 *
 * Defines the type system for the compound EnhancedSearch component.
 */

// Re-export types from sub-components
export type { SearchMode } from './components/SearchForm'
export type { SearchResult } from './components/SearchResults'
export type { ConfigTab, RetrievalMode } from './components/SearchConfig'

import type { SearchMode, SearchResult, RetrievalMode } from '.'

/**
 * Time range options for temporal search
 */
export type TimeRange = 'last30' | 'custom'

/**
 * View mode for results display
 */
export type ResultsViewMode = 'grid' | 'list'

/**
 * Custom time range definition
 */
export interface CustomTimeRange {
  since?: string
  until?: string
}

/**
 * Search history entry
 */
export interface SearchHistoryEntry {
  query: string
  mode: SearchMode
  timestamp: number
}

/**
 * Search parameters for different search modes
 */
export interface SearchParams {
  /** Search mode */
  searchMode: SearchMode
  /** Search query string */
  query: string
  /** Starting entity UUID for graph traversal */
  startEntityUuid: string
  /** Community UUID for community search */
  communityUuid: string
  /** Retrieval mode strategy */
  retrievalMode: RetrievalMode
  /** Search strategy */
  strategy: string
  /** Focal node UUID for node-distance retrieval */
  focalNode: string
  /** Cross-encoder model */
  crossEncoder: string
  /** Max depth for graph traversal */
  maxDepth: number
  /** Relationship types to filter */
  relationshipTypes: string[]
  /** Selected entity types */
  selectedEntityTypes: string[]
  /** Selected tags */
  selectedTags: string[]
  /** Include episodes in community search */
  includeEpisodes: boolean
  /** Time range for temporal search */
  timeRange: TimeRange
  /** Custom time range */
  customTimeRange: CustomTimeRange
  /** Project ID */
  projectId: string | undefined
}

/**
 * EnhancedSearch context shared across compound components
 */
export interface EnhancedSearchContextValue {
  /** Current search results */
  results: SearchResult[]
  /** Whether search is in progress */
  loading: boolean
  /** Error message if any */
  error: string | null
  /** Current search query */
  query: string
  /** Current search mode */
  searchMode: SearchMode
  /** Current view mode for results */
  viewMode: ResultsViewMode
  /** Whether config panel is open */
  isConfigOpen: boolean
  /** Whether results panel is collapsed */
  isResultsCollapsed: boolean
  /** Whether subgraph mode is active */
  isSubgraphMode: boolean
  /** Selected subgraph node IDs */
  selectedSubgraphIds: string[]
  /** Highlighted node IDs from results */
  highlightNodeIds: string[]
  /** Set query */
  setQuery: (query: string) => void
  /** Set search mode */
  setSearchMode: (mode: SearchMode) => void
  /** Set view mode */
  setViewMode: (mode: ResultsViewMode) => void
  /** Toggle config panel */
  toggleConfig: () => void
  /** Toggle results collapse */
  toggleResultsCollapse: () => void
  /** Toggle subgraph mode */
  toggleSubgraphMode: () => void
  /** Perform search */
  handleSearch: () => Promise<void>
  /** Set error */
  setError: (error: string | null) => void
}

/**
 * Props for the root EnhancedSearch component
 */
export interface EnhancedSearchRootProps {
  /** Project ID from route */
  projectId?: string
  /** Tenant ID */
  tenantId?: string
  /** Children for compound component pattern */
  children?: React.ReactNode
  /** Initial search mode */
  defaultSearchMode?: SearchMode
  /** Initial view mode */
  defaultViewMode?: ResultsViewMode
  /** Whether config is open by default */
  defaultConfigOpen?: boolean
}

/**
 * Props for Form sub-component
 */
export interface EnhancedSearchFormProps {
  /** Optional custom class name */
  className?: string
}

/**
 * Props for Config sub-component
 */
export interface EnhancedSearchConfigProps {
  /** Optional custom class name */
  className?: string
}

/**
 * Props for Results sub-component
 */
export interface EnhancedSearchResultsProps {
  /** Optional custom class name */
  className?: string
}

/**
 * Props for Graph sub-component
 */
export interface EnhancedSearchGraphProps {
  /** Optional custom class name */
  className?: string
}

/**
 * Props for Error sub-component
 */
export interface EnhancedSearchErrorProps {
  /** Optional custom class name */
  className?: string
}

/**
 * Props for History sub-component
 */
export interface EnhancedSearchHistoryProps {
  /** Optional custom class name */
  className?: string
}

/**
 * EnhancedSearch compound component interface
 * Extends React.FC with sub-component properties
 */
export interface EnhancedSearchCompound extends React.FC<EnhancedSearchRootProps> {
  /** Search form sub-component */
  Form: React.FC<EnhancedSearchFormProps>
  /** Configuration panel sub-component */
  Config: React.FC<EnhancedSearchConfigProps>
  /** Results list sub-component */
  Results: React.FC<EnhancedSearchResultsProps>
  /** Graph visualization sub-component */
  Graph: React.FC<EnhancedSearchGraphProps>
  /** Error message sub-component */
  Error: React.FC<EnhancedSearchErrorProps>
  /** Search history sub-component */
  History: React.FC<EnhancedSearchHistoryProps>
  /** Root component alias */
  Root: React.FC<EnhancedSearchRootProps>
}
